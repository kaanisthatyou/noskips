"""Making the widget listen — carefully.

WASAPI loopback lets us see what's actually coming out of the speakers, which
is what makes the visualiser real and the trace meaningful. It is also the most
dangerous thing in this codebase, for one specific reason:

    **a blocking read on a silent loopback device hangs forever.**

Nothing is playing, so no frames arrive, so `stream.read()` never returns — and
if that read is anywhere near the request path, the whole widget freezes. So
everything here is callback-driven: PortAudio hands us frames when it has them,
we do a little maths, and no thread the UI depends on ever waits on audio.

The rest of the defensiveness follows from the same instinct. Capture is off
until asked for, opening the device happens on its own thread, any failure
degrades to "not available" rather than raising, and the page falls back to a
procedural animation that looks alive without pretending to be listening.
"""

import base64
import math
import struct
import threading
import time

BANDS = 16
TRACE_POINTS = 240

# what counts as "loud" — dBFS floor for the band scaling
DB_FLOOR = -62.0
ATTACK = 0.55  # how fast a band jumps up
DECAY = 0.16  # ...and how slowly it falls, so it reads as music not noise


class Trace:
    """The shape of the sound, across one track.

    240 buckets spanning the song, each holding the loudest moment seen in it.
    Frozen when a verdict is stamped and stored beside it, so every rating
    carries the shape of what was actually playing when it was made.

    Deliberately cheap: 240 bytes, base64'd to ~320 characters, small enough to
    sit in a JSON file and a database column without anyone noticing.
    """

    def __init__(self, points=TRACE_POINTS):
        self.points = points
        self._lock = threading.Lock()
        self.key = ""
        self._peaks = bytearray(points)

    def reset(self, key):
        with self._lock:
            self.key = key
            self._peaks = bytearray(self.points)

    def feed(self, key, position, duration, level):
        """One observation: how loud it is, and how far into the track we are."""
        if not key or not duration or duration <= 0:
            return
        with self._lock:
            if key != self.key:
                self.key = key
                self._peaks = bytearray(self.points)
            index = int(max(0.0, min(0.999, position / duration)) * self.points)
            value = int(max(0.0, min(1.0, level)) * 255)
            if value > self._peaks[index]:
                self._peaks[index] = value

    def snapshot(self):
        """The trace so far, or None if we never heard anything.

        None matters: a trace is a claim about what was playing, so an empty one
        must not be stored as though it were a quiet song.
        """
        with self._lock:
            if not any(self._peaks):
                return None
            return base64.b64encode(bytes(self._peaks)).decode("ascii")


class Listen:
    """How much of a track was genuinely heard — not how long it was open.

    One slot per second of the song, set as the poller walks through it. The
    two rules the product cares about fall out of that shape rather than being
    special-cased:

    * **A rewind pays nothing.** Setting a slot that is already set is a no-op,
      so hearing the same chorus five times is worth one chorus.
    * **You cannot bank more than the song.** There are only as many slots as
      the track has seconds, so coverage is bounded by the track itself.

    A forward *seek* is not listening and is not credited: only the span the
    player actually moved through between two observations gets filled in, and
    only when that span is small enough to be playback rather than a jump.
    """

    # a poll lands about once a second; allow a little lateness before a gap
    # stops looking like playback and starts looking like a seek
    MAX_RUN = 4.0
    MAX_SECONDS = 3 * 60 * 60  # a slot array for a 3h DJ set is still tiny

    def __init__(self):
        self._lock = threading.Lock()
        self.key = ""
        self._heard = bytearray()
        self._duration = 0.0
        self._last_pos = None

    def reset(self, key="", duration=0.0):
        with self._lock:
            self._reset(key, duration)

    def _reset(self, key, duration):
        self.key = key
        self._duration = float(duration or 0.0)
        span = min(int(self._duration) + 1, self.MAX_SECONDS) if self._duration > 0 else 0
        self._heard = bytearray(span)
        self._last_pos = None

    def feed(self, key, position, duration):
        """One observation of where the playhead is."""
        if not key or not duration or duration <= 0:
            return
        with self._lock:
            if key != self.key or abs(float(duration) - self._duration) > 1.5:
                # a new track, or the player revised the length it reports
                self._reset(key, duration)
            if not self._heard:
                return

            pos = max(0.0, min(float(position), self._duration))
            last = self._last_pos
            self._last_pos = pos

            start = pos
            if last is not None and 0 <= pos - last <= self.MAX_RUN:
                # played through this stretch since the last look — credit it
                start = last
            first, last_slot = int(start), int(pos)
            for i in range(max(0, first), min(last_slot + 1, len(self._heard))):
                self._heard[i] = 1

    def _seconds(self):
        return sum(self._heard)

    def heard(self, key=None):
        """``(seconds_heard, coverage)`` for a track, or ``(0, 0.0)``.

        Passing the key you are about to stamp is the point: it refuses to hand
        you somebody else's listening for the song you happen to be rating.
        """
        with self._lock:
            if not self._heard or (key is not None and key != self.key):
                return 0, 0.0
            seconds = self._seconds()
            if self._duration <= 0:
                return seconds, 0.0
            return seconds, min(1.0, seconds / self._duration)


class Visualizer:
    """Loopback capture, or nothing at all — never a hang."""

    def __init__(self):
        self._lock = threading.Lock()
        self._bands = [0.0] * BANDS
        self._level = 0.0
        self._enabled = False
        self._available = False
        self._error = None
        self._opening = False
        self._frames_seen = 0
        self._pa = None
        self._stream = None
        self._edges = None
        self.trace = Trace()

    # ------------------------------------------------------------- state ----

    def status(self):
        with self._lock:
            return {
                "enabled": self._enabled,
                "available": self._available,
                "listening": self._frames_seen > 0,
                "error": self._error,
            }

    @property
    def enabled(self):
        return self._enabled

    def bands(self):
        with self._lock:
            return list(self._bands)

    def level(self):
        with self._lock:
            return self._level

    # ------------------------------------------------------------ control ----

    def enable(self, on):
        """Turn capture on or off. Returns immediately either way — opening a
        device can take a second and must never be done on a request."""
        if on and not self._enabled:
            self._enabled = True
            if not self._opening:
                self._opening = True
                threading.Thread(target=self._open, daemon=True, name="rateify-audio").start()
        elif not on and self._enabled:
            self._enabled = False
            self._close()
        return self.status()

    def _open(self):
        try:
            import numpy  # noqa: F401  — imported here so a missing dep is just "unavailable"
            import pyaudiowpatch as pyaudio
        except ImportError:
            return self._fail("audio capture isn't installed in this build")

        try:
            self._pa = pyaudio.PyAudio()
            api = self._pa.get_host_api_info_by_type(pyaudio.paWASAPI)
            speakers = self._pa.get_device_info_by_index(api["defaultOutputDevice"])

            loopback = None
            for info in self._pa.get_loopback_device_info_generator():
                if speakers["name"] in info["name"]:
                    loopback = info
                    break
            if loopback is None:
                return self._fail("no loopback device for the default speakers")

            rate = int(loopback["defaultSampleRate"])
            channels = min(2, int(loopback["maxInputChannels"])) or 1
            self._edges = _band_edges(rate)

            # callback mode: PortAudio calls us, we never call it and wait
            self._stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=rate,
                frames_per_buffer=1024,
                input=True,
                input_device_index=loopback["index"],
                stream_callback=self._on_frames(channels),
            )
            with self._lock:
                self._available = True
                self._error = None
        except Exception as exc:
            return self._fail(f"{type(exc).__name__}: {exc}")
        finally:
            self._opening = False

    def _fail(self, message):
        with self._lock:
            self._available = False
            self._error = message
        self._opening = False
        self._teardown()
        return None

    def _close(self):
        with self._lock:
            self._bands = [0.0] * BANDS
            self._level = 0.0
            self._frames_seen = 0
        self._teardown()

    def _teardown(self):
        stream, self._stream = self._stream, None
        pa, self._pa = self._pa, None
        for closer in (
            lambda: stream and stream.stop_stream(),
            lambda: stream and stream.close(),
            lambda: pa and pa.terminate(),
        ):
            try:
                closer()
            except Exception:
                pass  # tearing down a broken device must not raise

    # ------------------------------------------------------------- frames ----

    def _on_frames(self, channels):
        import numpy as np

        window = np.hanning(1024)
        # An unnormalised rfft bin sums 1024 samples, so a full-scale tone comes
        # out around +48dB and every band pegs at 1.0 — a visualiser that's
        # always maxed reads as broken. Scaling by the window's own sum puts a
        # full-scale sine at 0dB, where the dB floor below can do its job.
        gain = 2.0 / np.sum(window)

        def callback(in_data, frame_count, time_info, status):
            import pyaudiowpatch as pyaudio

            if not self._enabled:
                return (None, pyaudio.paComplete)
            try:
                samples = np.frombuffer(in_data, dtype=np.int16).astype(np.float32) / 32768.0
                if channels > 1:
                    samples = samples.reshape(-1, channels).mean(axis=1)
                if len(samples) < len(window):
                    samples = np.pad(samples, (0, len(window) - len(samples)))
                block = samples[: len(window)] * window

                spectrum = np.abs(np.fft.rfft(block)) * gain
                bands = [
                    float(spectrum[lo:hi].max()) if hi > lo else 0.0
                    for lo, hi in self._edges
                ]
                scaled = [_to_unit(value) for value in bands]
                rms = float(np.sqrt(np.mean(samples**2)))

                with self._lock:
                    for i, value in enumerate(scaled):
                        previous = self._bands[i]
                        # fast attack, slow decay: bars that fall like a VU meter
                        rate = ATTACK if value > previous else DECAY
                        self._bands[i] = previous + (value - previous) * rate
                    # rms straight through: loud music sits around -20..-10dBFS,
                    # which lands at 0.65-0.85 against the floor below
                    self._level = _to_unit(rms)
                    self._frames_seen += 1
            except Exception:
                pass  # a bad frame is not worth killing the stream over
            return (None, pyaudio.paContinue)

        return callback


def _band_edges(rate, bands=BANDS, lo_hz=40.0, hi_hz=16000.0, size=1024):
    """Log-spaced bins — the ear hears octaves, so linear bands would put almost
    everything in the first two bars."""
    bin_hz = rate / size
    edges = []
    for i in range(bands):
        lo = lo_hz * (hi_hz / lo_hz) ** (i / bands)
        hi = lo_hz * (hi_hz / lo_hz) ** ((i + 1) / bands)
        lo_bin = int(lo / bin_hz)
        hi_bin = max(lo_bin + 1, int(hi / bin_hz))
        edges.append((lo_bin, min(hi_bin, size // 2)))
    return edges


def _to_unit(magnitude):
    """Magnitude to 0..1 on a dB scale, because loudness isn't linear."""
    if magnitude <= 1e-9:
        return 0.0
    db = 20 * math.log10(magnitude)
    return max(0.0, min(1.0, (db - DB_FLOOR) / -DB_FLOOR))


# --------------------------------------------------------------- fallback ----


def procedural_bands(position, duration, seed=0, bands=BANDS):
    """What the mini bar does when it isn't really listening.

    Looks alive, claims nothing. Deterministic from the position so it doesn't
    jitter randomly between polls, and deliberately *not* fed into the trace —
    a trace means "this is what it sounded like", and inventing one would make
    the honest ones worthless.
    """
    if not duration:
        return [0.0] * bands
    t = position * 2.4
    out = []
    for i in range(bands):
        phase = (i + 1) * 0.7 + seed
        wobble = math.sin(t * (0.8 + i * 0.11) + phase) * 0.5 + 0.5
        tilt = 1.0 - (i / bands) * 0.45  # music has less energy up top
        out.append(round(max(0.03, wobble * tilt), 3))
    return out


def trace_to_points(encoded, width=100.0, height=24.0):
    """Decode a stored trace into SVG polyline points."""
    try:
        raw = base64.b64decode(encoded or "")
    except (ValueError, TypeError):
        return ""
    if not raw:
        return ""
    step = width / max(1, len(raw) - 1)
    return " ".join(
        f"{i * step:.2f},{height - (value / 255) * height:.2f}"
        for i, value in enumerate(struct.unpack(f"{len(raw)}B", raw))
    )
