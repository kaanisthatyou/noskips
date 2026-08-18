"""Cover art served with the headers Cover Art Archive never sends.

The thing under test is the promise: one request, cacheable for a year, and no
stored bytes anywhere. The upstream is always faked — a test suite that reaches
coverartarchive.org is a test suite that fails when someone else's server is
slow.
"""

import pytest

from server.web import art_src


class FakeRaw:
    def __init__(self, body):
        self._body = body

    def read(self, size, decode_content=True):
        return self._body[:size]


class FakeResponse:
    def __init__(self, status=200, body=b"\xff\xd8\xff-jpeg-bytes", headers=None):
        self.status_code = status
        self.headers = headers or {"Content-Type": "image/jpeg", "ETag": '"abc123"'}
        self.raw = FakeRaw(body)


MBID = "ae229bdd-2179-440c-bc78-acf0952914d4"
STORED = f"https://coverartarchive.org/release-group/{MBID}/front-500"


# ------------------------------------------------------------- the rewrite ----


def test_a_stored_cover_points_at_our_own_copy():
    assert art_src(STORED) == f"/art/{MBID}/front.jpg"


def test_nothing_to_show_stays_nothing():
    assert art_src(None) is None
    assert art_src("") is None


def test_a_url_we_do_not_recognise_is_left_alone():
    """This must never be able to turn a working image into a 404."""
    other = "https://example.com/some/other/cover.jpg"
    assert art_src(other) == other


def test_a_caa_url_of_another_shape_is_left_alone():
    release = "https://coverartarchive.org/release/xyz/front-250"
    assert art_src(release) == release


# --------------------------------------------------------------- the route ----


def test_the_art_route_sends_a_year_of_immutable(client, monkeypatch):
    monkeypatch.setattr("server.web.art.requests.get", lambda *a, **k: FakeResponse())
    r = client.get(f"/art/{MBID}/front.jpg")
    assert r.status_code == 200
    assert r.mimetype == "image/jpeg"
    cache = r.headers["Cache-Control"]
    assert "public" in cache and "immutable" in cache
    assert "max-age=31536000" in cache
    # the CDN is told separately so the two can diverge later
    assert "immutable" in r.headers["CDN-Cache-Control"]


def test_the_bytes_come_straight_through(client, monkeypatch):
    monkeypatch.setattr(
        "server.web.art.requests.get", lambda *a, **k: FakeResponse(body=b"JPEGDATA")
    )
    assert client.get(f"/art/{MBID}/front.jpg").data == b"JPEGDATA"


def test_a_revalidating_browser_gets_a_304(client, monkeypatch):
    monkeypatch.setattr("server.web.art.requests.get", lambda *a, **k: FakeResponse())
    r = client.get(f"/art/{MBID}/front.jpg", headers={"If-None-Match": '"abc123"'})
    assert r.status_code == 304
    assert r.data == b""


def test_a_string_that_is_not_an_mbid_never_reaches_upstream(client, monkeypatch):
    def explode(*a, **k):  # pragma: no cover — the point is that it isn't called
        raise AssertionError("built a URL from unvalidated input")

    monkeypatch.setattr("server.web.art.requests.get", explode)
    for bad in ("../../etc/passwd", "not-an-mbid", "x" * 36):
        assert client.get(f"/art/{bad}/front.jpg").status_code == 404


def test_no_art_upstream_is_a_404_not_a_broken_image(client, monkeypatch):
    monkeypatch.setattr(
        "server.web.art.requests.get", lambda *a, **k: FakeResponse(status=404)
    )
    assert client.get(f"/art/{MBID}/front.jpg").status_code == 404


def test_upstream_being_down_does_not_500(client, monkeypatch):
    import requests

    def boom(*a, **k):
        raise requests.RequestException("connection reset")

    monkeypatch.setattr("server.web.art.requests.get", boom)
    assert client.get(f"/art/{MBID}/front.jpg").status_code == 404


def test_something_that_is_not_an_image_is_refused(client, monkeypatch):
    monkeypatch.setattr(
        "server.web.art.requests.get",
        lambda *a, **k: FakeResponse(headers={"Content-Type": "text/html"}),
    )
    assert client.get(f"/art/{MBID}/front.jpg").status_code == 404


def test_an_absurdly_large_body_is_refused(client, monkeypatch):
    from server.web import art

    monkeypatch.setattr(art, "MAX_BYTES", 16)
    monkeypatch.setattr(
        "server.web.art.requests.get", lambda *a, **k: FakeResponse(body=b"x" * 64)
    )
    assert client.get(f"/art/{MBID}/front.jpg").status_code == 404


# ------------------------------------------------------------ nothing kept ----


def test_the_database_still_holds_only_a_url(db):
    """The whole point: caching, not hosting. If a column ever starts holding
    image bytes this is the test that should stop it."""
    from server.models import Work

    col = Work.__table__.c.cover_url
    assert col.type.length == 300, "a cover column is a link, not a payload"
    assert not any(
        c.type.__class__.__name__ in ("LargeBinary", "BLOB")
        for c in Work.__table__.columns
    ), "no binary column belongs on works"
