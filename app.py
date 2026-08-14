"""noskips — tiny local widget that shows what Spotify is playing and lets you rate it.

Reads Windows' media session (SMTC), so no Spotify API keys are needed.
Run:  python app.py   → opens http://127.0.0.1:7700
"""
__version__ = "2.0.0"

import asyncio
import hashlib
import json
import os
import shutil
import socket
import sys
import threading
import time
import webbrowser
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, send_from_directory

import media_kind
from audio import Visualizer, procedural_bands
from sync import SyncEngine

from winrt.windows.media.control import (
    GlobalSystemMediaTransportControlsSessionManager as SessionManager,
    GlobalSystemMediaTransportControlsSessionPlaybackStatus as PlaybackStatus,
)
from winrt.windows.storage.streams import Buffer, InputStreamOptions

# frozen exe: bundled read-only assets live in _MEIPASS, data next to the exe
FROZEN = getattr(sys, "frozen", False)
BUNDLE = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
ROOT = Path(sys.executable).parent if FROZEN else Path(__file__).parent
# NOSKIPS_DATA_DIR relocates the library. Mostly this exists so the tests can
# run against a throwaway folder instead of the real one — without it there is
# no way to import this module without pointing it at whoever's library happens
# to be next to the source, which is exactly the accident it was added after.
DATA_DIR = Path(os.environ.get("NOSKIPS_DATA_DIR") or (ROOT / "data"))
COVERS_DIR = Path(os.environ.get("NOSKIPS_COVERS_DIR") or (ROOT / "covers"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
COVERS_DIR.mkdir(parents=True, exist_ok=True)
RATINGS_FILE = DATA_DIR / "ratings.json"
# Videos live in their own file, in the same format. Two stores rather than one
# with a flag, because it makes the important guarantee structural: the sync
# engine is only ever handed the music store, so a video *cannot* reach the
# shared index by accident. Nothing has to remember to check a field.
VIDEOS_FILE = DATA_DIR / "videos.json"

PORT = 7700


def _migrate_from_rateify():
    """This app used to be called Rateify and installed to its own folder, so an
    upgrader's library sits next to the *old* exe. Copy it across on first run.

    Deliberately a copy, not a move: the old install keeps working until they
    uninstall it, and nobody loses a library to a half-finished migration.
    """
    if RATINGS_FILE.exists() or (DATA_DIR / ".migrated-from-rateify").exists():
        return
    local = os.environ.get("LOCALAPPDATA")
    if not local:
        return
    legacy = Path(local) / "Programs" / "Rateify"
    if not (legacy / "data" / "ratings.json").exists():
        return
    try:
        shutil.copy2(legacy / "data" / "ratings.json", RATINGS_FILE)
        if (legacy / "covers").is_dir():
            shutil.copytree(legacy / "covers", COVERS_DIR, dirs_exist_ok=True)
        (DATA_DIR / ".migrated-from-rateify").write_text(
            f"copied from {legacy} on {datetime.now().isoformat(timespec='seconds')}\n",
            encoding="utf-8",
        )
    except OSError:
        pass  # a failed migration must never stop the app from starting


_migrate_from_rateify()

app = Flask(__name__, static_folder=str(BUNDLE / "static"), static_url_path="")

# ---------------------------------------------------------------- ratings ----

_ratings_lock = threading.Lock()


def _store_file(kind):
    """Which file a verdict belongs in — see media_kind.store_for for why."""
    return VIDEOS_FILE if media_kind.store_for(kind) == media_kind.VIDEO else RATINGS_FILE


def _load(kind=media_kind.MUSIC):
    path = _store_file(kind)
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"albums": {}}


def _save(data, kind=media_kind.MUSIC):
    _store_file(kind).write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def _album_key(artist, album):
    return f"{artist}:::{album}"


def _album_avg(album):
    values = [t["value"] for t in album["tracks"].values()]
    return round(sum(values) / len(values), 2) if values else None


def _library_as_ops():
    """Every stored *music* rating, as sync ops — used once, right after
    pairing, so a shelf built up over months shows up on the account instead of
    only the tracks rated from then on.

    It reads the music store and nothing else, which is the whole reason videos
    get their own file: they can't be leaked by forgetting a condition here.
    """
    with _ratings_lock:
        data = _load(media_kind.MUSIC)
    return [
        {
            "op": "rate",
            "artist": entry["artist"],
            "album": entry["album"],
            "title": title,
            "value": info["value"],
            "label": info["label"],
            "note": info.get("note", ""),
            "trace": info.get("trace"),
            "rev": int(info.get("rev", 1)),
            "rated_at": info.get("date"),
            "updated_at": info.get("date"),
            "is_public": info.get("public", True),
            "note_public": info.get("notePublic", True),
        }
        for entry in data["albums"].values()
        for title, info in entry["tracks"].items()
    ]


# The social half. Dormant until the user pairs a device and switches sync on —
# until then it opens no connections at all.
SYNC = SyncEngine(
    DATA_DIR, app_version=__version__, library_provider=_library_as_ops
).start()

# Listening is off until asked for. See audio.py for why every part of it is
# written to fail into "not available" rather than to block.
VIS = Visualizer()


# ------------------------------------------------------------ SMTC worker ----

_now_lock = threading.Lock()
_now = {"active": False}
_session = None  # latest SMTC session, used by /api/control
_loop = None  # worker thread's asyncio loop


def _cover_path(artist, album):
    h = hashlib.md5(f"{artist}|{album}".encode("utf-8")).hexdigest()[:16]
    return COVERS_DIR / f"{h}.png"


async def _grab_cover(info, path):
    if path.exists() or not info.thumbnail:
        return
    stream = await info.thumbnail.open_read_async()
    size = stream.size
    if not size:
        return
    buf = Buffer(size)
    await stream.read_async(buf, size, InputStreamOptions.READ_AHEAD)
    path.write_bytes(bytes(buf))


async def _poll_forever():
    global _session
    mgr = await SessionManager.request_async()
    while True:
        try:
            session = None
            for s in mgr.get_sessions():
                if "spotify" in (s.source_app_user_model_id or "").lower():
                    session = s
                    break
            if session is None:
                session = mgr.get_current_session()
            _session = session

            if session is None:
                snap = {"active": False}
            else:
                info = await session.try_get_media_properties_async()
                pb = session.get_playback_info()
                tl = session.get_timeline_properties()
                artist = info.artist or ""
                album = info.album_title or ""
                title = info.title or ""
                source = session.source_app_user_model_id or ""
                kind = media_kind.classify(
                    info, pb, source_app=source, album=album, artist=artist
                )

                cover = ""
                if title:
                    cpath = _cover_path(artist, album)
                    try:
                        await _grab_cover(info, cpath)
                    except OSError:
                        pass
                    if cpath.exists():
                        cover = f"/covers/{cpath.name}"
                # SMTC tells us when the reported position was accurate; use
                # that as the timestamp so the client can extrapolate exactly
                pos_ts = time.time()
                try:
                    lu = tl.last_updated_time
                    if lu and lu.year > 2000:
                        pos_ts = lu.timestamp()
                except (OSError, OverflowError, ValueError):
                    pass
                snap = {
                    "active": bool(title),
                    "title": title,
                    "artist": artist,
                    "album": album,
                    "kind": kind,
                    "source": source,
                    "playing": pb.playback_status == PlaybackStatus.PLAYING,
                    "position": tl.position.total_seconds() if tl.position else 0,
                    "duration": tl.end_time.total_seconds() if tl.end_time else 0,
                    "cover": cover,
                    "ts": pos_ts,
                }
            with _now_lock:
                _now.clear()
                _now.update(snap)

            # one observation per second, which is about one per trace bucket
            # on a four-minute song — the resolution the trace was sized for
            if snap.get("active") and VIS.enabled:
                VIS.trace.feed(
                    f"{snap['artist']}:::{snap['album']}:::{snap['title']}",
                    snap.get("position", 0),
                    snap.get("duration", 0),
                    VIS.level(),
                )
        except Exception as exc:  # keep the poller alive no matter what
            with _now_lock:
                _now.clear()
                _now.update({"active": False, "error": str(exc)})
        await asyncio.sleep(1.0)


def _worker():
    global _loop
    _loop = asyncio.new_event_loop()
    asyncio.set_event_loop(_loop)
    _loop.run_until_complete(_poll_forever())


# ------------------------------------------------------------------ routes ----


@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.get("/covers/<path:name>")
def cover(name):
    return send_from_directory(COVERS_DIR, name)


@app.get("/api/now")
def api_now():
    with _now_lock:
        snap = dict(_now)
    if snap.get("active"):
        with _ratings_lock:
            data = _load(snap.get("kind"))
        album = data["albums"].get(_album_key(snap["artist"], snap["album"]))
        saved = album["tracks"].get(snap["title"]) if album else None
        snap["saved"] = saved
        # what everyone else made of it — from cache, so this never blocks and
        # stays None until the answer arrives (or forever, if sync is off).
        # Videos have no shared side at all, so we never even ask.
        snap["shared"] = (
            None
            if snap.get("kind") == media_kind.VIDEO
            else SYNC.shared_for(snap["artist"], snap["album"], snap["title"])
        )
    return jsonify(snap)


_ACTIONS = {
    "playpause": "try_toggle_play_pause_async",
    "next": "try_skip_next_async",
    "prev": "try_skip_previous_async",
}


@app.post("/api/control")
def api_control():
    action = (request.get_json(silent=True) or {}).get("action")
    session = _session
    if action not in _ACTIONS or session is None or _loop is None:
        return jsonify(ok=False), 400
    async def _do():
        # winrt methods return an IAsyncOperation, not a coroutine — await it here
        return await getattr(session, _ACTIONS[action])()

    fut = asyncio.run_coroutine_threadsafe(_do(), _loop)
    try:
        ok = fut.result(timeout=5)
    except Exception:
        ok = False
    return jsonify(ok=bool(ok))


def _is_playing_now(artist, album, title):
    """Was this actually spinning when they stamped it?

    That's the difference between a 'live' verdict and one typed from memory,
    and it's the only claim the shared world treats as special.
    """
    with _now_lock:
        snap = dict(_now)
    return bool(
        snap.get("active")
        and snap.get("title") == title
        and snap.get("artist") == artist
        and snap.get("album") == album
    )


def _kind_now(title, fallback=media_kind.MUSIC):
    """What Windows says is playing, for a verdict being stamped on it."""
    with _now_lock:
        snap = dict(_now)
    if snap.get("active") and snap.get("title") == title:
        return snap.get("kind") or fallback
    return fallback


@app.post("/api/rate")
def api_rate():
    body = request.get_json(force=True)
    artist, album, title = body["artist"], body["album"], body["title"]
    # the client passes what it was shown; the live session is the tiebreaker
    kind = body.get("kind") or _kind_now(title)
    if kind not in (media_kind.MUSIC, media_kind.VIDEO, media_kind.UNKNOWN, media_kind.IMAGE):
        kind = media_kind.MUSIC
    key = _album_key(artist, album)
    with _ratings_lock:
        data = _load(kind)
        entry = data["albums"].setdefault(
            key, {"artist": artist, "album": album, "cover": "", "tracks": {}}
        )
        cpath = _cover_path(artist, album)
        if cpath.exists():
            entry["cover"] = f"/covers/{cpath.name}"
        previous = entry["tracks"].get(title) or {}
        # The trace: the shape of the sound at the moment of the verdict.
        # Only ever recorded when we were genuinely listening to this track —
        # a trace claims "this is what it sounded like", and an invented one
        # would make every honest one worthless.
        live = _is_playing_now(artist, album, title)
        trace = None
        if live and VIS.enabled and VIS.trace.key == f"{artist}:::{album}:::{title}":
            trace = VIS.trace.snapshot()

        record = {
            "value": round(float(body["value"]), 2),
            "label": body["label"],
            "note": body.get("note", "").strip(),
            "date": datetime.now().isoformat(timespec="seconds"),
            "trace": trace or previous.get("trace"),
            # kept on the record as well as implied by the file, so the shape
            # survives being copied, merged or hand-edited
            "kind": kind,
            # a local revision counter, so a queued op can never be overtaken by
            # an older one that happened to reach the server later
            "rev": int(previous.get("rev", 0)) + 1,
            "public": bool(body.get("public", True)),
            "notePublic": bool(body.get("notePublic", True)),
        }
        entry["tracks"][title] = record
        _save(data, kind)
        avg = _album_avg(entry)

    # Videos stop here. They keep a shelf of their own on this machine, but the
    # shared index is meant to be songs somebody stopped and judged, and a
    # channel's upload is not that.
    if kind == media_kind.VIDEO:
        return jsonify(ok=True, albumAvg=avg, kind=kind, shared=False, sync=SYNC.status())

    # Queued outside the lock, and the queue is local — the button is already done
    SYNC.enqueue(
        {
            "op": "rate",
            "artist": artist,
            "album": album,
            "title": title,
            "value": record["value"],
            "label": record["label"],
            "note": record["note"],
            "trace": record["trace"],
            "rev": record["rev"],
            "rated_at": record["date"],
            "updated_at": record["date"],
            "is_public": record["public"],
            "note_public": record["notePublic"],
            "provenance": "live" if live else "web",
        }
    )
    return jsonify(ok=True, albumAvg=avg, sync=SYNC.status())


@app.delete("/api/rate")
def api_unrate():
    body = request.get_json(force=True)
    artist, album, title = body["artist"], body["album"], body["title"]
    key = _album_key(artist, album)
    removed = None
    removed_from = media_kind.MUSIC

    with _ratings_lock:
        # the caller may not know which shelf it was on, so try both rather than
        # make the UI keep track
        for store in (body.get("kind"), media_kind.MUSIC, media_kind.VIDEO):
            if store is None:
                continue
            data = _load(store)
            entry = data["albums"].get(key)
            if entry and title in entry["tracks"]:
                removed = entry["tracks"].pop(title)
                if not entry["tracks"]:
                    del data["albums"][key]
                _save(data, store)
                removed_from = store
                break

    # only music was ever sent, so only music needs withdrawing
    if removed is not None and removed_from != media_kind.VIDEO:
        SYNC.enqueue(
            {
                "op": "unrate",
                "artist": artist,
                "album": album,
                "title": title,
                "rev": int(removed.get("rev", 0)) + 1,
            }
        )
    return jsonify(ok=True, sync=SYNC.status())


def _shelf(kind):
    """One store, in the shape the shelf renders."""
    with _ratings_lock:
        data = _load(kind)
    albums = []
    for entry in data["albums"].values():
        tracks = [
            {"title": t, **info}
            for t, info in sorted(
                entry["tracks"].items(), key=lambda kv: kv[1]["date"], reverse=True
            )
        ]
        albums.append(
            {
                "artist": entry["artist"],
                "album": entry["album"],
                "cover": entry["cover"],
                "avg": _album_avg(entry),
                "count": len(tracks),
                "latest": max(t["date"] for t in tracks),
                "tracks": tracks,
                "kind": kind,
            }
        )
    albums.sort(key=lambda a: a["latest"], reverse=True)
    return albums


@app.get("/api/library")
def api_library():
    # `albums` keeps its old name and meaning so nothing that already reads this
    # endpoint changes; videos arrive alongside it as their own shelf.
    return jsonify(
        albums=_shelf(media_kind.MUSIC),
        videos=_shelf(media_kind.VIDEO),
    )


# -------------------------------------------------------------- visualizer ----


@app.get("/api/visual")
def api_visual():
    return jsonify(VIS.status())


@app.post("/api/visual")
def api_visual_toggle():
    on = bool((request.get_json(silent=True) or {}).get("on", True))
    return jsonify(VIS.enable(on))


@app.get("/api/spectrum")
def api_spectrum():
    """Sixteen bands, streamed.

    Server-sent events rather than a socket: the page stays a dumb consumer, no
    Web Audio, no permission prompt, and if this connection dies the widget
    carries on completely unaffected.
    """
    def frames():
        while True:
            if VIS.enabled and VIS.status()["available"]:
                bands = VIS.bands()
            else:
                # not listening — send the honest procedural shape instead
                with _now_lock:
                    snap = dict(_now)
                bands = (
                    procedural_bands(snap.get("position", 0), snap.get("duration", 0))
                    if snap.get("active") and snap.get("playing")
                    else []
                )
            yield f"data: {json.dumps(bands)}\n\n"
            time.sleep(1 / 24)

    return app.response_class(
        frames(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ----------------------------------------------------------------- account ----
# All of these are local calls into the sync engine. The ones that touch the
# network say so, and none of them are on the path of rating a song.


@app.get("/api/account")
def api_account():
    return jsonify(SYNC.status())


@app.post("/api/account/pair")
def api_account_pair():
    """Ask the server for a code, then open the browser at the link page —
    which is where the actual signing in happens."""
    try:
        pairing = SYNC.begin_pairing()
    except Exception as exc:
        return jsonify(ok=False, error=f"couldn't reach the server ({exc.__class__.__name__})"), 502
    webbrowser.open(pairing["url"])
    return jsonify(ok=True, **pairing, sync=SYNC.status())


@app.post("/api/account/cancel")
def api_account_cancel():
    SYNC.cancel_pairing()
    return jsonify(ok=True, sync=SYNC.status())


@app.post("/api/account/signout")
def api_account_signout():
    SYNC.sign_out()
    return jsonify(ok=True, sync=SYNC.status())


@app.post("/api/account/sync")
def api_account_sync():
    on = bool((request.get_json(silent=True) or {}).get("on", True))
    SYNC.set_enabled(on)
    return jsonify(ok=True, sync=SYNC.status())


def _acquire_singleton():
    """Claim the port with our own bind, rather than testing it with a
    connect() — a connect-based check leaves a race window during this
    instance's own Flask startup where a second near-simultaneous launch
    also sees the port as free, so both survive as separate windows.
    A bind is atomic: only one process can ever hold it, immediately."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", PORT))
    except OSError:
        s.close()
        return None
    s.listen(8)
    return s


def _run_flask(lock_socket):
    from werkzeug.serving import make_server

    make_server("127.0.0.1", PORT, app, fd=lock_socket.fileno()).serve_forever()


def _run_widget(lock_socket):
    """Frameless always-on-top widget window; the page's header is the drag
    handle and its ✕ / — buttons call back in through window.expose."""
    import webview

    threading.Thread(target=_run_flask, args=(lock_socket,), daemon=True).start()
    window = webview.create_window(
        "noskips",
        f"http://127.0.0.1:{PORT}",
        width=420,
        height=560,
        frameless=True,
        on_top=True,
        resizable=True,
        background_color="#f0e9d8",
        transparent=True,  # lets the tucked-away mini bar show the desktop through it
        min_size=(150, 40),  # default is (200, 100) — taller than our 40px mini bar,
        # so the window used to refuse to shrink past 100px, leaving blank space below it
    )

    def close():
        window.destroy()

    def minimize():
        window.minimize()

    def resize(width, height):
        # the page asks to be fitted to its content (drawer open/closed, etc.)
        window.resize(int(width), int(height))

    window.expose(close, minimize, resize)
    webview.start()  # blocks until the window is closed


if __name__ == "__main__":
    lock_socket = _acquire_singleton()
    if lock_socket is None:
        # another noskips already holds the port — just bring up its page
        webbrowser.open(f"http://127.0.0.1:{PORT}")
        sys.exit(0)
    threading.Thread(target=_worker, daemon=True).start()
    try:
        _run_widget(lock_socket)
    except Exception:
        # no WebView2 runtime? fall back to the browser like the old days
        threading.Timer(1.0, lambda: webbrowser.open(f"http://127.0.0.1:{PORT}")).start()
        print(f"noskips spinning at http://127.0.0.1:{PORT}")
        _run_flask(lock_socket)
