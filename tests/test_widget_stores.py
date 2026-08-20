"""Two shelves in the widget: songs and videos.

A video is rated exactly like a song — nothing is turned away. It just lands in
data/videos.json instead of data/ratings.json, and the sync engine is only ever
handed the music store. These tests hold that boundary, because the failure is
silent: a video reaching the shared index would create a `work` for everybody
and nobody would notice until it was on an album page.
"""

import importlib
import json
import sys

import pytest

SONG = {"artist": "Tame Impala", "album": "Currents", "title": "Let It Happen"}
VIDEO = {"artist": "Some Channel", "album": "", "title": "i built a pc in a toaster"}


@pytest.fixture
def widget(tmp_path, monkeypatch):
    """A fresh widget app with its library in a throwaway folder.

    app.py resolves DATA_DIR at import time from RATEIFY_DATA_DIR, so the env
    has to be set *before* the reimport. The assertion below is not paranoia:
    an earlier version of this fixture used monkeypatch.chdir, which does
    nothing here because the path is derived from __file__ — and the tests
    cheerfully wrote into the real library instead.
    """
    data = tmp_path / "data"
    monkeypatch.setenv("RATEIFY_DATA_DIR", str(data))
    monkeypatch.setenv("RATEIFY_COVERS_DIR", str(tmp_path / "covers"))
    for name in ("app", "sync", "audio", "media_kind"):
        sys.modules.pop(name, None)

    import app as widget_app

    widget_app = importlib.reload(widget_app)

    assert widget_app.DATA_DIR == data, (
        f"refusing to run: the widget is pointed at {widget_app.DATA_DIR}, "
        "which is not this test's temp folder"
    )

    # never let a test reach the network, whatever the sync engine decides
    monkeypatch.setattr(widget_app.SYNC, "enqueue", _recorder(widget_app))
    return widget_app


def _recorder(widget_app):
    widget_app.queued = []

    def enqueue(op):
        widget_app.queued.append(op)

    return enqueue


def rate(client, media, value=8.0, **extra):
    return client.post(
        "/api/rate",
        json={**media, "value": value, "label": str(value), **extra},
    )


def read(widget_app, name):
    path = widget_app.DATA_DIR / name
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


# ------------------------------------------------------------ where it lands ----


def test_a_song_goes_to_the_music_store(widget):
    rate(widget.app.test_client(), SONG)

    assert read(widget, "ratings.json") is not None
    assert read(widget, "videos.json") is None


def test_a_video_goes_to_its_own_file(widget):
    rate(widget.app.test_client(), VIDEO, kind="video")

    videos = read(widget, "videos.json")
    assert videos is not None
    entry = next(iter(videos["albums"].values()))
    assert entry["tracks"]["i built a pc in a toaster"]["kind"] == "video"
    # and it did not touch the music shelf
    assert read(widget, "ratings.json") is None


def test_an_unknown_kind_is_filed_as_music(widget):
    rate(widget.app.test_client(), SONG, kind="unknown")

    assert read(widget, "ratings.json") is not None
    assert read(widget, "videos.json") is None


def test_a_song_and_a_video_can_share_a_name(widget):
    client = widget.app.test_client()
    same = {"artist": "x", "album": "", "title": "Nightcall"}

    rate(client, same, 9.0)
    rate(client, same, 3.0, kind="video")

    music = read(widget, "ratings.json")
    videos = read(widget, "videos.json")
    assert next(iter(music["albums"].values()))["tracks"]["Nightcall"]["value"] == 9.0
    assert next(iter(videos["albums"].values()))["tracks"]["Nightcall"]["value"] == 3.0


# ---------------------------------------------------------------- never shared ----


def test_a_video_is_never_queued_for_sync(widget):
    rate(widget.app.test_client(), VIDEO, kind="video")

    assert widget.queued == []


def test_a_song_is_queued_for_sync(widget):
    rate(widget.app.test_client(), SONG)

    assert [op["title"] for op in widget.queued] == ["Let It Happen"]


def test_the_backfill_never_sees_videos(widget):
    """Pairing lifts your shelf to the account. It reads the music store and
    nothing else, so a video cannot be leaked by a forgotten condition."""
    client = widget.app.test_client()
    rate(client, SONG)
    rate(client, VIDEO, kind="video")

    ops = widget._library_as_ops()

    assert [op["title"] for op in ops] == ["Let It Happen"]


def test_unrating_a_video_does_not_send_a_withdrawal(widget):
    client = widget.app.test_client()
    rate(client, VIDEO, kind="video")
    widget.queued.clear()

    client.delete("/api/rate", json={**VIDEO, "kind": "video"})

    assert widget.queued == []
    assert read(widget, "videos.json")["albums"] == {}


def test_unrating_a_song_still_withdraws_it(widget):
    client = widget.app.test_client()
    rate(client, SONG)
    widget.queued.clear()

    client.delete("/api/rate", json=SONG)

    assert [op["op"] for op in widget.queued] == ["unrate"]


def test_unrate_finds_the_right_shelf_without_being_told(widget):
    """The shelf UI shouldn't have to track which file a row came from."""
    client = widget.app.test_client()
    rate(client, VIDEO, kind="video")

    client.delete("/api/rate", json=VIDEO)  # no kind given

    assert read(widget, "videos.json")["albums"] == {}


# ---------------------------------------------------------------- the library ----


def test_the_library_returns_both_shelves_separately(widget):
    client = widget.app.test_client()
    rate(client, SONG)
    rate(client, VIDEO, kind="video")

    body = client.get("/api/library").get_json()

    assert [a["album"] for a in body["albums"]] == ["Currents"]
    assert len(body["videos"]) == 1
    assert body["videos"][0]["kind"] == "video"
    assert body["albums"][0]["kind"] == "music"


def test_an_empty_library_still_answers_both_shelves(widget):
    body = widget.app.test_client().get("/api/library").get_json()
    assert body == {"albums": [], "videos": []}
