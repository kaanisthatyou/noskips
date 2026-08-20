"""The front door: search, recent, and rating from the web.

Before this existed you could only reach an album page if somebody handed you
the link, and the only way to add a verdict was the Windows widget. These are
the seams that turn the server into something a stranger can actually walk
into, so they're tested as HTTP rather than as functions.
"""

import pytest

from tests.test_api import SONG, rate, signup


def rate_song(client, artist, album, title, value=8.0, **extra):
    op = {
        "op": "rate",
        "artist": artist,
        "album": album,
        "title": title,
        "value": value,
        "label": str(value),
        **extra,
    }
    r = client.post("/v1/sync", json={"ops": [op]})
    assert r.status_code == 200, r.get_json()
    return r.get_json()["results"][0]


# ------------------------------------------------------------------ search ----


def test_search_finds_a_song_by_half_its_title(client):
    signup(client)
    rate(client)

    hits = client.get("/v1/search?q=happen").get_json()

    assert [w["title"] for w in hits["works"]] == ["Let It Happen"]
    assert hits["albums"][0]["album"] == "Currents"


@pytest.mark.parametrize("query", ["tame impala", "TAME IMPALA", "currents", "Let It Happen"])
def test_search_matches_artist_album_and_title(client, query):
    signup(client)
    rate(client)

    assert client.get(f"/v1/search?q={query}").get_json()["works"]


def test_search_folds_the_query_the_same_way_the_index_was_folded(client):
    """A pasted title carries edition noise the stored row doesn't have."""
    signup(client)
    rate(client)

    hits = client.get("/v1/search?q=Let It Happen - 2015 Remaster").get_json()

    assert [w["title"] for w in hits["works"]] == ["Let It Happen"]


def test_search_ignores_accents_the_way_the_index_does(client):
    signup(client)
    rate_song(client, "Beyoncé", "Lemonade", "Formation")

    assert client.get("/v1/search?q=beyonce").get_json()["works"]


def test_a_wildcard_does_not_match_the_whole_index(client):
    """% is a LIKE wildcard; typed into a search box it is just a character."""
    signup(client)
    rate(client)

    assert client.get("/v1/search?q=%").get_json()["works"] == []
    assert client.get("/v1/search?q=%%").get_json()["works"] == []


def test_a_one_letter_query_searches_nothing(client):
    """Short enough to match half the index, so it isn't a search — and the
    page says so rather than dumping everything."""
    signup(client)
    rate(client)

    assert client.get("/v1/search?q=a").get_json()["works"] == []


def test_search_only_finds_songs_somebody_actually_rated(client):
    """The one rule, as a search result: unrating the last verdict takes the
    song back out of the world, so it must stop being findable."""
    signup(client)
    rate(client)
    assert client.get("/v1/search?q=happen").get_json()["works"]

    client.post("/v1/sync", json={"ops": [{"op": "unrate", **SONG}]})

    assert client.get("/v1/search?q=happen").get_json()["works"] == []


def test_search_finds_people_by_handle(client):
    signup(client)

    assert [u["handle"] for u in client.get("/v1/search?q=kaan").get_json()["people"]] == ["kaan"]


def test_a_private_shelf_is_still_findable_by_name(client):
    """That somebody exists isn't the secret — what's on their shelf is, and
    the profile page already refuses to show it."""
    signup(client)
    client.patch("/v1/me", json={"is_private": True})

    assert client.get("/v1/search?q=kaan").get_json()["people"]


def test_a_banned_account_is_not_findable(client, db):
    from server.models import User

    signup(client)
    db.query(User).filter(User.handle_ci == "kaan").one().is_banned = True
    db.commit()

    assert client.get("/v1/search?q=kaan").get_json()["people"] == []


def test_matching_tracks_are_grouped_into_the_record_they_sit_on(client):
    signup(client)
    for track in ("Nangs", "The Moment", "Yes I'm Changing"):
        rate_song(client, "Tame Impala", "Currents", track)

    albums = client.get("/v1/search?q=tame").get_json()["albums"]

    assert len(albums) == 1
    assert albums[0]["rated_tracks"] == 3


def test_the_search_page_renders_and_offers_a_first_press_on_a_miss(client):
    body = client.get("/search?q=something+nobody+rated").data.decode()

    assert "nothing here yet" in body
    assert "be its first press" in body


def test_the_search_box_is_in_the_chrome_of_every_page(client):
    """A shared index you can't search is a filing cabinet with no handle."""
    for path in ("/", "/recent", "/login"):
        assert b'action="/search"' in client.get(path).data


# ------------------------------------------------------------------ recent ----


def test_recent_lists_the_newest_verdicts(client):
    signup(client)
    rate(client, note="a real banger")

    verdicts = client.get("/v1/recent").get_json()["verdicts"]

    assert verdicts[0]["work"]["title"] == "Let It Happen"
    assert verdicts[0]["note"] == "a real banger"


def test_recent_leaves_out_verdicts_kept_off_the_shelf(client):
    signup(client)
    rate(client, is_public=False)

    assert client.get("/v1/recent").get_json()["verdicts"] == []


def test_a_public_verdict_on_a_private_shelf_stays_off_the_public_list(client):
    """The combination that leaks: the rating is public, the person isn't."""
    signup(client)
    rate(client)
    client.patch("/v1/me", json={"is_private": True})

    assert client.get("/v1/recent").get_json()["verdicts"] == []


def test_a_junk_limit_is_a_typo_not_a_500(client):
    signup(client)  # so the feed gets past auth and actually parses the limit

    assert client.get("/v1/recent?limit=lots").status_code == 200
    assert client.get("/v1/feed?limit=lots").status_code == 200


def test_the_recent_page_renders_for_a_stranger(client):
    signup(client)
    rate(client)
    stranger = client.application.test_client()

    assert b"Let It Happen" in stranger.get("/recent").data


def test_an_empty_index_says_somebody_has_to_go_first(client):
    assert b"nothing stamped yet" in client.get("/recent").data


# ------------------------------------------------------- rating on the web ----


def test_you_can_stamp_a_song_from_the_web(client):
    signup(client)

    result = rate_song(client, "Tame Impala", "Currents", "Let It Happen", 9.0)

    assert result["status"] == "stored"
    assert result["first_press"] is True
    # the page you get sent to afterwards — only the server knows which record
    # a freshly-normalized title landed on
    assert client.get(f"/album/{result['album_key']}").status_code == 200


def test_a_web_verdict_is_marked_web_not_live(client, db):
    """Only a paired widget may claim it was stamped while the track played.
    That mark is the whole value of the mark."""
    from server.models import Rating

    signup(client)
    rate_song(client, "Tame Impala", "Currents", "Let It Happen", provenance="live")

    assert db.query(Rating).one().provenance == "web"


def test_the_album_page_offers_a_stamp_control_to_a_signed_in_reader(client):
    signup(client)
    rate(client)
    album_key = client.get("/v1/u/kaan/shelf").get_json()["verdicts"][0]["work"]["album_key"]

    body = client.get(f"/album/{album_key}").data.decode()

    assert "stamp-control" in body
    # they've already judged this one, so it offers to change the number
    assert "restamp it" in body


def test_a_stranger_is_offered_the_way_in_rather_than_a_dead_control(client):
    signup(client)
    rate(client)
    album_key = client.get("/v1/u/kaan/shelf").get_json()["verdicts"][0]["work"]["album_key"]
    stranger = client.application.test_client()

    body = stranger.get(f"/album/{album_key}").data.decode()

    assert "stamp-control" not in body
    assert "get the widget" in body


def test_restamping_from_the_web_replaces_rather_than_duplicates(client, db):
    from server.models import Rating

    signup(client)
    rate_song(client, "Tame Impala", "Currents", "Let It Happen", 6.0)
    rate_song(client, "Tame Impala", "Currents", "Let It Happen", 9.0)

    rating = db.query(Rating).one()
    assert float(rating.value) == 9.0


def test_a_later_web_verdict_wins_against_the_revision_the_widget_left(client, db):
    """The web control sends the widget's revision back rather than one past
    it, so recency settles the argument. If it sent a higher number, a verdict
    the widget stamped afterwards would be silently dropped."""
    from server.models import Rating

    signup(client)
    rate_song(client, "Tame Impala", "Currents", "Let It Happen", 6.0, rev=4)

    result = rate_song(client, "Tame Impala", "Currents", "Let It Happen", 9.0, rev=4)

    assert result["status"] == "stored"
    assert float(db.query(Rating).one().value) == 9.0


def test_the_stamp_page_needs_a_name_first(client):
    assert client.get("/stamp").headers["Location"] == "/login?next=/stamp"

    signup(client, handle=None)
    assert client.get("/stamp").headers["Location"] == "/welcome"

    client.post("/v1/handle/claim", json={"handle": "kaan"})
    assert client.get("/stamp").status_code == 200


def test_the_stamp_page_prefills_from_a_missed_search(client):
    signup(client)

    body = client.get("/stamp?title=Let+It+Happen&artist=Tame+Impala").data.decode()

    assert 'value="Let It Happen"' in body
    assert 'value="Tame Impala"' in body


# ------------------------------------------------------------- the landing ----


def test_the_landing_page_leads_with_the_one_rule(client):
    body = client.get("/").data.decode()

    assert "judge every song" in body
    assert "nobody has rated this yet" in body
    assert "download for windows" in body


def test_the_ticker_stays_hidden_until_it_would_look_alive(client, app):
    """Three lonely rows read as abandoned. Better no section at all."""
    signup(client)
    rate(client)
    stranger = app.test_client()

    assert b"what people are saying" not in stranger.get("/").data


def test_the_ticker_appears_once_there_is_enough_to_show(client, app):
    from server.web.pages import TICKER_FLOOR

    signup(client)
    for n in range(TICKER_FLOOR):
        rate_song(client, "Tame Impala", "Currents", f"Track {n}")
    stranger = app.test_client()

    assert b"what people are saying" in stranger.get("/").data


def test_the_download_page_says_windows_only_up_front(client):
    """Finding this out after a 30MB download wastes a Mac user's afternoon."""
    body = client.get("/download").data.decode()

    assert "Windows 10/11 only" in body
    assert "rateify-Setup-" in body


def test_the_privacy_page_says_what_never_leaves_the_machine(client):
    body = client.get("/privacy").data.decode()

    assert "videos never sync" in body
    assert "/settings" in body  # how to delete it all


def test_the_footer_is_on_every_page(client):
    assert b'href="/privacy"' in client.get("/").data
    assert b'href="/privacy"' in client.get("/login").data


def test_the_site_link_preview_card_renders(client):
    from server.web import og

    if not og.enabled():
        pytest.skip("Pillow not installed")

    r = client.get("/og/site.png")
    assert r.status_code == 200 and r.mimetype == "image/png"


# ------------------------------------------------------------ housekeeping ----


def test_spent_rate_limit_windows_are_pruned(session):
    """They're keyed by IP address, so they don't get to live forever."""
    from datetime import timedelta

    from server.models import RateLimit, utcnow
    from server.security import prune_rate_limits

    session.add(RateLimit(bucket="login:1.2.3.4", window_start=utcnow() - timedelta(days=2), count=9))
    session.add(RateLimit(bucket="login:5.6.7.8", window_start=utcnow(), count=1))
    session.flush()

    assert prune_rate_limits(session) == 1
    assert [r.bucket for r in session.query(RateLimit)] == ["login:5.6.7.8"]


def test_the_ticker_is_cached_as_html_not_as_rows(client, app):
    """Rows cached across requests are detached ORM objects: the first render
    happens to load their relationships, and the day a template touches one it
    didn't is a DetachedInstanceError in production and nowhere else. So the
    fragment is cached, and it has to survive being served again."""
    from server.web.pages import TICKER_FLOOR

    signup(client)
    for n in range(TICKER_FLOOR + 1):
        rate_song(client, "Tame Impala", "Currents", f"Track {n}", note=f"note {n}")
    stranger = app.test_client()

    first = stranger.get("/").data.decode()
    second = stranger.get("/").data.decode()

    # the newest verdict, and its note — proof the fragment went through the
    # same macro every other page uses rather than some landing-page stub
    assert f"note {TICKER_FLOOR}" in first
    assert first == second
    assert app.extensions["ticker_cache"]["html"]


def test_a_strangers_front_page_may_be_held_by_a_cdn(client):
    """It's the same bytes for everybody and the most-hit url on the site."""
    assert client.get("/").headers["Cache-Control"] == "public, max-age=120"


def test_attacker_controlled_strings_are_escaped_on_the_new_pages(client):
    """Track names come from whatever the player put in its tags, and the
    stamp control puts them back out again as data attributes."""
    xss = "<script>alert(1)</script>"
    signup(client)
    rate_song(client, xss, xss, xss, note=xss)
    album_key = client.get("/v1/u/kaan/shelf").get_json()["verdicts"][0]["work"]["album_key"]

    for path in ("/search?q=script", "/recent", f"/album/{album_key}", f"/stamp?title={xss}"):
        assert "<script>alert" not in client.get(path).data.decode(), path

    body = client.get(f"/album/{album_key}").data.decode()
    assert 'data-artist="&lt;script&gt;' in body


def test_a_private_note_stays_off_the_public_list(client, app):
    signup(client)
    rate(client, note="kept back", note_public=False)
    stranger = app.test_client()

    assert b"kept back" not in stranger.get("/recent").data
    assert b"kept back" in client.get("/recent").data  # but it's still yours


# ------------------------------------------------------------- the database ----


@pytest.mark.parametrize(
    "given,expected",
    [
        # what Neon actually puts on your clipboard
        (
            "postgresql://u:p@ep-x-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require",
            "postgresql+psycopg://u:p@ep-x-pooler.eu-central-1.aws.neon.tech/neondb?sslmode=require",
        ),
        # the legacy scheme SQLAlchemy dropped, still handed out by Heroku
        ("postgres://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        # a driver chosen on purpose is left alone
        ("postgresql+psycopg2://u:p@h/db", "postgresql+psycopg2://u:p@h/db"),
        ("postgresql+psycopg://u:p@h/db", "postgresql+psycopg://u:p@h/db"),
        ("sqlite:///rateify-dev.db", "sqlite:///rateify-dev.db"),
    ],
)
def test_a_pasted_connection_string_is_made_connectable(given, expected):
    """`postgresql://` with no driver resolves to psycopg2, and what's installed
    is psycopg 3 — so pasting Neon's URL unchanged is a ModuleNotFoundError
    from alembic and from the first request in production."""
    from server.db import normalize_database_url

    assert normalize_database_url(given) == expected


def test_the_migrations_connect_the_same_way_the_app_does():
    """A migration that resolves a different URL from the server is its own bug,
    so env.py shares the whole helper rather than repeating any of it.

    It used to share only ``normalize_database_url`` and keep its own copy of
    the ``sqlite:///rateify-dev.db`` fallback — which meant the blank-means-unset
    fix had to be made in two places, and one of them would have been missed.
    """
    from pathlib import Path

    env = Path("server/migrations/env.py").read_text(encoding="utf-8")

    assert "from server.db import database_url" in env
    assert "postgres://" not in env  # no second, drifting copy of the rewrite
    assert "sqlite:///" not in env  # nor of the fallback
    assert "DATABASE_URL" not in env.split('"""', 2)[-1]  # nor of the lookup
