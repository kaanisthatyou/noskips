"""The widget's sync engine, tested against the real server.

The point of these is the three promises in sync.py's docstring — rating never
waits on the network, nothing leaves the machine until you ask, and the local
file stays the source of truth. Those are exactly the properties that quietly
rot, so they get tested against a live app rather than a mock.
"""

import json

import pytest
import requests

from server.models import Rating, Work
from sqlalchemy import func, select

SONG = ("Tame Impala", "Currents", "Let It Happen")


class LocalTransport(requests.adapters.BaseAdapter):
    """Routes the sync engine's HTTP straight into the Flask test client, so
    there's a real server on the other end but no socket."""

    def __init__(self, client):
        super().__init__()
        self.client = client
        self.offline = False
        self.calls = []

    def send(self, request, **kwargs):
        if self.offline:
            raise requests.ConnectionError("offline")
        self.calls.append(request.url)

        path = request.url.split("://", 1)[-1].split("/", 1)[-1]
        body = request.body
        if isinstance(body, bytes):
            body = body.decode("utf-8")
        method = request.method.lower()
        headers = {k: v for k, v in request.headers.items() if k.lower() == "authorization"}

        flask_response = getattr(self.client, method)(
            f"/{path}",
            data=body,
            headers={**headers, "Content-Type": "application/json"},
        )
        response = requests.Response()
        response.status_code = flask_response.status_code
        response._content = flask_response.data
        response.url = request.url
        response.headers["Content-Type"] = "application/json"
        response.request = request
        return response

    def close(self):
        pass


@pytest.fixture
def engine(tmp_path, app, monkeypatch):
    """A sync engine wired to the real app.

    Deliberately its own test client, with its own (empty) cookie jar: a real
    widget has no browser session and authenticates purely with its device
    token. Sharing the browser's client would let a cookie stand in for the
    token and quietly hide token bugs.
    """
    from sync import SyncEngine

    monkeypatch.setattr("sync.TICK", 0.01)

    data_dir = tmp_path / "widgetdata"
    data_dir.mkdir()
    eng = SyncEngine(data_dir, base_url="http://server", app_version="2.0.0")

    transport = LocalTransport(app.test_client())
    eng._http.mount("http://", transport)
    eng.transport = transport
    return eng


def sign_up_and_pair(engine, client, app):
    """Do the whole pairing dance the way the widget really does."""
    client.post("/v1/auth/signup", json={"email": "kaan@example.com", "password": "a good long one"})
    client.post("/v1/handle/claim", json={"handle": "kaan"})

    started = engine.begin_pairing()
    client.post("/link", data={"code": started["code"].replace("-", "")})
    engine._poll_pairing()
    return started


def rate_op(value=8.0, **extra):
    artist, album, title = SONG
    return {
        "op": "rate", "artist": artist, "album": album, "title": title,
        "value": value, "label": str(value), "rev": 1, **extra,
    }


# ------------------------------------------------------- nothing leaks early ----


def test_a_fresh_widget_makes_no_requests_at_all(engine):
    """Signed out is genuinely silent — not 'silent except telemetry'."""
    engine.enqueue(rate_op())
    engine._drain()
    engine._fetch_shared()

    assert engine.transport.calls == []
    assert engine.status()["signed_in"] is False


def test_shared_lookups_are_refused_while_signed_out(engine):
    """Asking what the world thinks would tell the world what you're playing."""
    assert engine.shared_for(*SONG) is None
    assert engine.transport.calls == []


def test_a_signed_out_widget_queues_nothing(engine):
    """No account to send to, so no shadow copy of the shelf. Signing in
    backfills from ratings.json instead."""
    engine.enqueue(rate_op())

    assert engine.status()["unsent"] == 0
    assert not engine.outbox_file.exists()


def test_pairing_backfills_the_shelf_you_already_had(engine, client, app, db):
    """The moment that has to feel good: sign in and months of verdicts are
    already there, rather than only what you rate from now on."""
    engine.library_provider = lambda: [
        {**rate_op(9.0), "title": "Let It Happen"},
        {**rate_op(6.0), "title": "Eventually"},
    ]

    sign_up_and_pair(engine, client, app)
    engine._drain()

    assert db.scalar(select(func.count()).select_from(Work)) == 2


def test_backfilled_ratings_never_claim_to_be_live(engine, client, app, db):
    """We can't prove we watched those play, and 'live' only means anything if
    it's never claimed loosely."""
    engine.library_provider = lambda: [rate_op(9.0, provenance="live")]

    sign_up_and_pair(engine, client, app)
    engine._drain()

    assert db.scalar(select(Rating.provenance)) == "web"


# ---------------------------------------------------------------- pairing ----


def test_pairing_signs_the_widget_in(engine, client, app):
    started = sign_up_and_pair(engine, client, app)

    assert "-" in started["code"]
    status = engine.status()
    assert status["signed_in"] is True
    assert status["handle"] == "kaan"


def test_sync_can_be_paused_without_signing_out(engine, client, app):
    sign_up_and_pair(engine, client, app)
    engine.set_enabled(False)

    engine.enqueue(rate_op())
    engine._drain()

    assert engine.status()["signed_in"] is True
    assert engine.status()["unsent"] == 1  # still queued, nothing sent


# ------------------------------------------------------------------ drain ----


def test_queued_ratings_reach_the_server(engine, client, app, db):
    sign_up_and_pair(engine, client, app)
    engine.enqueue(rate_op(9.0))

    engine._drain()

    assert engine.status()["unsent"] == 0
    assert db.scalar(select(func.count()).select_from(Work)) == 1
    assert float(db.scalar(select(Rating.value))) == 9.0


def test_offline_keeps_the_queue_and_says_so(engine, client, app):
    sign_up_and_pair(engine, client, app)
    engine.transport.offline = True

    engine.enqueue(rate_op())
    engine._drain()

    status = engine.status()
    assert status["unsent"] == 1
    assert "offline" in status["last_error"]


def test_coming_back_online_drains_the_backlog(engine, client, app, db):
    sign_up_and_pair(engine, client, app)
    engine.transport.offline = True
    for i, title in enumerate(["Let It Happen", "Eventually", "The Less I Know"]):
        engine.enqueue({**rate_op(7.0), "title": title})
    engine._drain()
    assert engine.status()["unsent"] == 3

    engine.transport.offline = False
    engine._drain()

    assert engine.status()["unsent"] == 0
    assert db.scalar(select(func.count()).select_from(Work)) == 3


def test_only_the_newest_verdict_per_track_is_queued(engine, client, app):
    """Re-stamping five times offline shouldn't send five ops."""
    sign_up_and_pair(engine, client, app)
    engine.transport.offline = True
    for value in (1.0, 4.0, 6.0, 8.0, 10.0):
        engine.enqueue(rate_op(value, rev=int(value)))

    outbox = json.loads(engine.outbox_file.read_text())
    assert len(outbox) == 1
    assert outbox[0]["value"] == 10.0


def test_a_rejected_op_does_not_wedge_the_queue(engine, client, app):
    sign_up_and_pair(engine, client, app)
    engine.enqueue({**rate_op(), "value": 99.0})  # server will refuse this

    engine._drain()

    assert engine.status()["unsent"] == 0  # answered means finished, not retried


def test_unrate_reaches_the_server_and_removes_the_work(engine, client, app, db):
    sign_up_and_pair(engine, client, app)
    engine.enqueue(rate_op())
    engine._drain()
    assert db.scalar(select(func.count()).select_from(Work)) == 1

    artist, album, title = SONG
    engine.enqueue({"op": "unrate", "artist": artist, "album": album, "title": title, "rev": 2})
    engine._drain()

    assert db.scalar(select(func.count()).select_from(Work)) == 0


# ----------------------------------------------------------------- shared ----


def test_first_press_is_reported_for_an_unrated_song(engine, client, app):
    sign_up_and_pair(engine, client, app)

    assert engine.shared_for(*SONG) is None  # nothing cached yet
    engine._fetch_shared()

    assert engine.shared_for(*SONG) == {"exists": False, "first_press": True}


def test_shared_average_appears_once_somebody_has_rated(engine, client, app):
    sign_up_and_pair(engine, client, app)
    engine.enqueue(rate_op(8.0))
    engine._drain()

    engine.shared_for(*SONG)
    engine._fetch_shared()
    shared = engine.shared_for(*SONG)

    assert shared["exists"] is True
    assert shared["average"] == 8.0 and shared["count"] == 1


def test_rating_invalidates_the_cached_community_figure(engine, client, app):
    sign_up_and_pair(engine, client, app)
    engine.shared_for(*SONG)
    engine._fetch_shared()
    assert engine.shared_for(*SONG)["exists"] is False

    engine.enqueue(rate_op(8.0))

    assert engine.shared_for(*SONG) is None  # stale answer dropped, not shown


# ------------------------------------------------------------- signing out ----


def test_signing_out_forgets_the_account_but_not_your_ratings(engine, client, app):
    sign_up_and_pair(engine, client, app)
    engine.sign_out()

    status = engine.status()
    assert status["signed_in"] is False
    assert status["handle"] is None
    assert not engine.session_file.read_text().strip("{} \n")


def test_a_revoked_device_stops_syncing_but_keeps_the_queue(engine, client, app, db):
    from server.auth import pairing as pairing_mod
    from server.models import Device

    sign_up_and_pair(engine, client, app)
    pairing_mod.revoke(db, db.scalars(select(Device)).first())
    db.commit()

    engine.enqueue(rate_op())
    engine._drain()

    status = engine.status()
    assert status["signed_in"] is False
    assert status["unsent"] == 1  # kept: pair again and it all still goes out
