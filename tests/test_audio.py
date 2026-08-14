"""The visualiser and the trace.

Real loopback capture can't be exercised in a test — there's no audio playing
and, as the hang that prompted callback mode showed, waiting for some would
block forever. So what's tested here is everything around it: the maths, the
bucketing, the honesty rule (no capture, no trace), and above all that nothing
in this module can hang or raise into the widget.
"""

import base64

import pytest

from audio import (
    BANDS,
    TRACE_POINTS,
    Trace,
    Visualizer,
    _band_edges,
    _to_unit,
    procedural_bands,
    trace_to_points,
)

# --------------------------------------------------------------------- maths ----


def test_band_edges_are_log_spaced_and_ascending():
    edges = _band_edges(48000)
    assert len(edges) == BANDS
    widths = [hi - lo for lo, hi in edges]
    # the ear hears octaves: high bands must cover far more bins than low ones
    assert widths[-1] > widths[0]
    assert all(hi > lo for lo, hi in edges)


def test_band_edges_stay_inside_the_spectrum():
    for rate in (44100, 48000, 96000):
        assert all(hi <= 512 for _lo, hi in _band_edges(rate))


def test_silence_is_zero_and_full_scale_is_one():
    assert _to_unit(0) == 0.0
    assert _to_unit(1e-12) == 0.0
    assert _to_unit(1.0) == 1.0


def test_loudness_is_monotonic():
    values = [_to_unit(v) for v in (0.001, 0.01, 0.1, 1.0)]
    assert values == sorted(values)


# ------------------------------------------------------------------- trace ----


def test_a_trace_starts_empty():
    assert Trace().snapshot() is None


def test_an_empty_trace_is_none_not_a_quiet_song():
    """Storing all-zeros would claim we listened and heard silence."""
    trace = Trace()
    trace.feed("song", 10, 200, 0.0)
    assert trace.snapshot() is None


def test_feeding_builds_a_trace():
    trace = Trace()
    trace.feed("song", 100, 200, 0.8)

    raw = base64.b64decode(trace.snapshot())
    assert len(raw) == TRACE_POINTS
    assert raw[TRACE_POINTS // 2] == int(0.8 * 255)


def test_each_bucket_keeps_the_loudest_moment():
    trace = Trace()
    trace.feed("song", 100, 200, 0.3)
    trace.feed("song", 100, 200, 0.9)
    trace.feed("song", 100, 200, 0.4)

    raw = base64.b64decode(trace.snapshot())
    assert raw[TRACE_POINTS // 2] == int(0.9 * 255)


def test_changing_track_starts_a_fresh_trace():
    trace = Trace()
    trace.feed("first", 100, 200, 0.9)
    trace.feed("second", 10, 200, 0.5)

    raw = base64.b64decode(trace.snapshot())
    assert trace.key == "second"
    assert raw[TRACE_POINTS // 2] == 0  # the old song's peak is gone


def test_positions_past_the_end_do_not_overflow():
    trace = Trace()
    trace.feed("song", 500, 200, 1.0)  # a position beyond the duration
    assert len(base64.b64decode(trace.snapshot())) == TRACE_POINTS


def test_a_track_with_no_duration_is_ignored():
    """SMTC reports zero duration for streams and briefly on track changes."""
    trace = Trace()
    trace.feed("song", 10, 0, 1.0)
    assert trace.snapshot() is None


def test_trace_survives_a_round_trip_to_svg_points():
    trace = Trace()
    for i in range(0, 200, 10):
        trace.feed("song", i, 200, i / 200)

    points = trace_to_points(trace.snapshot())

    assert points.count(",") == TRACE_POINTS
    first_x = float(points.split(",")[0])
    assert first_x == 0.0


def test_broken_trace_data_renders_nothing_rather_than_raising():
    """This string arrives from a database row that some other client wrote."""
    for junk in (None, "", "not base64!!", "%%%%"):
        assert trace_to_points(junk) == ""


# ------------------------------------------------------------- procedural ----


def test_procedural_bands_look_alive_but_claim_nothing():
    bands = procedural_bands(30.0, 200.0)
    assert len(bands) == BANDS
    assert all(0 <= v <= 1 for v in bands)
    assert len(set(bands)) > 1  # not a flat line


def test_procedural_bands_are_deterministic():
    """Otherwise the bars jitter randomly between polls instead of moving."""
    assert procedural_bands(30.0, 200.0) == procedural_bands(30.0, 200.0)


def test_procedural_bands_move_over_time():
    assert procedural_bands(30.0, 200.0) != procedural_bands(31.0, 200.0)


def test_procedural_bands_handle_a_missing_duration():
    assert procedural_bands(10.0, 0) == [0.0] * BANDS


# -------------------------------------------------------------- visualizer ----


def test_a_visualizer_starts_off_and_silent():
    vis = Visualizer()
    status = vis.status()
    assert status["enabled"] is False
    assert status["available"] is False
    assert vis.bands() == [0.0] * BANDS
    assert vis.level() == 0.0


def test_disabling_when_never_enabled_is_harmless():
    assert Visualizer().enable(False)["enabled"] is False


def test_enable_returns_immediately(monkeypatch):
    """Opening a device can take seconds; enable() must never be the thing that
    waits for it, or the settings toggle freezes the widget."""
    import audio

    started = {}

    class FakeThread:
        def __init__(self, target, **kwargs):
            started["target"] = target

        def start(self):
            started["started"] = True

    monkeypatch.setattr(audio.threading, "Thread", FakeThread)

    vis = Visualizer()
    status = vis.enable(True)

    assert status["enabled"] is True
    assert started["started"] is True  # handed off, not run inline


def test_a_missing_audio_dependency_degrades_to_unavailable(monkeypatch):
    """A build without pyaudiowpatch must still run — just without listening."""
    import builtins

    real_import = builtins.__import__

    def no_audio(name, *args, **kwargs):
        if name in ("pyaudiowpatch", "numpy"):
            raise ImportError(name)
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_audio)

    vis = Visualizer()
    vis._enabled = True
    vis._open()

    status = vis.status()
    assert status["available"] is False
    assert "isn't installed" in status["error"]


def test_a_broken_device_degrades_instead_of_raising(monkeypatch):
    import audio

    class Exploding:
        def __init__(self):
            raise OSError("device in use")

    monkeypatch.setitem(
        __import__("sys").modules, "pyaudiowpatch", type("m", (), {"PyAudio": Exploding})
    )

    vis = Visualizer()
    vis._enabled = True
    vis._open()  # must not raise

    assert vis.status()["available"] is False
    assert "device in use" in vis.status()["error"]
