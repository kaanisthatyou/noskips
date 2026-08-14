"""The MusicBrainz resolver.

No network: every test stubs the HTTP layer, because a test suite that phones a
volunteer-run service on every run is both slow and rude.

The merge tests carry most of the weight. Folding two works together moves
ratings between rows that have a UNIQUE(user_id, work_id) constraint on them,
so the case where one person rated both spellings is a real constraint
violation waiting to happen — and the aggregates have to survive it.
"""

import pytest
from sqlalchemy import func, select

from server import musicbrainz as mb
from server.models import Rating, Work
from server.store import first_press, upsert_rating

SONG = ("The Killers", "Hot Fuss", "Mr. Brightside")
SAME_SONG_OTHER_SPELLING = ("The Killers", "Hot Fuss", "Mister Brightside")


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """Any un-stubbed request is a test bug, not a slow test."""
    def explode(*args, **kwargs):
        raise AssertionError("a test tried to reach the network")

    monkeypatch.setattr(mb, "_throttled", explode)


def stub(monkeypatch, recordings=None, cover_status=307):
    calls = []

    def fake(method, url, **kwargs):
        calls.append((method, url))

        class Response:
            status_code = cover_status if method == "HEAD" else 200

            def raise_for_status(self):
                pass

            def json(self):
                return {"recordings": recordings or []}

        return Response()

    monkeypatch.setattr(mb, "_throttled", fake)
    return calls


def a_recording(score=95, rid="rec-1", group="rg-1"):
    return {
        "id": rid,
        "score": score,
        "releases": [{"release-group": {"id": group}}] if group else [],
    }


# ------------------------------------------------------------------ lookup ----


def test_a_confident_match_is_used(monkeypatch):
    stub(monkeypatch, [a_recording()])
    assert mb.lookup_recording("The Killers", "Mr. Brightside") == {
        "recording": "rec-1",
        "release_group": "rg-1",
    }


def test_a_weak_match_is_ignored(monkeypatch):
    """A bad merge is much worse than no merge — it puts verdicts on the wrong
    recording and there's no way for anyone to tell."""
    stub(monkeypatch, [a_recording(score=40)])
    assert mb.lookup_recording("The Killers", "Mr. Brightside") is None


def test_lucene_characters_in_titles_do_not_break_the_query(monkeypatch):
    calls = stub(monkeypatch, [a_recording()])
    assert mb.lookup_recording("AC/DC", 'T.N.T. (Live) [Remix]: "Loud"') is not None
    assert calls  # it built a query rather than raising


def test_a_dead_service_resolves_to_nothing(monkeypatch):
    import requests

    def down(*args, **kwargs):
        raise requests.ConnectionError("musicbrainz is having a day")

    monkeypatch.setattr(mb, "_throttled", down)
    assert mb.lookup_recording("x", "y") is None


def test_missing_artist_or_title_never_asks(monkeypatch):
    assert mb.lookup_recording("", "y") is None
    assert mb.lookup_recording("x", "") is None


def test_cover_art_is_checked_not_assumed(monkeypatch):
    stub(monkeypatch, cover_status=307)
    assert mb.cover_url("rg-1").endswith("/release-group/rg-1/front-500")

    stub(monkeypatch, cover_status=404)
    assert mb.cover_url("rg-1") is None  # no broken images on album pages


# --------------------------------------------------------------- resolution ----


def test_resolving_stamps_the_mbid_and_cover(session, users, monkeypatch):
    upsert_rating(session, users[0], *SONG, value=9.0, label="9")
    work = session.scalar(select(Work))
    stub(monkeypatch, [a_recording()])

    assert mb.resolve_work(session, work) is True

    assert work.mbid_recording == "rec-1"
    assert work.cover_url.endswith("/release-group/rg-1/front-500")
    assert work.pending_resolution is False


def test_an_unresolvable_work_is_not_retried_forever(session, users, monkeypatch):
    upsert_rating(session, users[0], *SONG, value=9.0, label="9")
    work = session.scalar(select(Work))
    stub(monkeypatch, [])

    assert mb.resolve_work(session, work) is False
    assert work.pending_resolution is False
    assert work.mbid_recording is None  # still a perfectly usable work


def test_the_drain_reports_what_it_did(session, users, monkeypatch):
    upsert_rating(session, users[0], *SONG, value=9.0, label="9")
    stub(monkeypatch, [a_recording()])

    assert mb.resolve_pending(session) == {"attempted": 1, "resolved": 1}
    # and it doesn't pick the same work up again
    assert mb.resolve_pending(session) == {"attempted": 0, "resolved": 0}


# ------------------------------------------------------------------ merging ----


def test_two_spellings_of_one_song_merge(session, users, monkeypatch):
    upsert_rating(session, users[0], *SONG, value=9.0, label="9")
    upsert_rating(session, users[1], *SAME_SONG_OTHER_SPELLING, value=7.0, label="7")
    assert session.scalar(select(func.count()).select_from(Work)) == 2

    stub(monkeypatch, [a_recording()])
    mb.resolve_pending(session)

    survivors = [w for w in session.scalars(select(Work)) if w.merged_into is None]
    assert len(survivors) == 1
    assert survivors[0].rating_count == 2
    assert survivors[0].average == 8.0


def test_the_old_key_still_resolves_after_a_merge(session, users, monkeypatch):
    """Widgets in the wild are still holding the old key."""
    from server.store import get_work

    upsert_rating(session, users[0], *SONG, value=9.0, label="9")
    upsert_rating(session, users[1], *SAME_SONG_OTHER_SPELLING, value=7.0, label="7")
    losing_key = session.scalars(select(Work.work_key)).all()

    stub(monkeypatch, [a_recording()])
    mb.resolve_pending(session)

    for key in losing_key:
        found = get_work(session, key)
        assert found is not None and found.merged_into is None


def test_merging_keeps_the_first_press_with_whoever_was_first(session, users, monkeypatch):
    from datetime import datetime, timedelta, timezone

    t0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
    upsert_rating(session, users[0], *SONG, value=9.0, label="9", rated_at=t0)
    upsert_rating(
        session, users[1], *SAME_SONG_OTHER_SPELLING, value=7.0, label="7",
        rated_at=t0 + timedelta(days=1),
    )

    stub(monkeypatch, [a_recording()])
    mb.resolve_pending(session)

    winner = next(w for w in session.scalars(select(Work)) if w.merged_into is None)
    assert first_press(session, winner).handle == "kaan"


def test_one_person_who_rated_both_spellings_keeps_their_latest(session, users, monkeypatch):
    """The constraint-violation case: UNIQUE(user_id, work_id) means only one of
    their two verdicts can survive the merge."""
    from datetime import datetime, timedelta, timezone

    t0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
    upsert_rating(session, users[0], *SONG, value=3.0, label="3", updated_at=t0)
    upsert_rating(
        session, users[0], *SAME_SONG_OTHER_SPELLING, value=9.0, label="9",
        updated_at=t0 + timedelta(days=1),
    )
    assert session.scalar(select(func.count()).select_from(Rating)) == 2

    stub(monkeypatch, [a_recording()])
    mb.resolve_pending(session)

    winner = next(w for w in session.scalars(select(Work)) if w.merged_into is None)
    assert winner.rating_count == 1
    assert winner.average == 9.0  # the one they changed their mind to
    assert session.scalar(select(func.count()).select_from(Rating)) == 1


def test_aggregates_are_recounted_not_added(session, users, monkeypatch):
    """After a merge with a clash the two denormalized counts no longer agree,
    so they have to be recomputed from the ratings themselves."""
    from datetime import datetime, timedelta, timezone

    t0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
    upsert_rating(session, users[0], *SONG, value=4.0, label="4", updated_at=t0)
    upsert_rating(session, users[1], *SONG, value=6.0, label="6")
    upsert_rating(
        session, users[0], *SAME_SONG_OTHER_SPELLING, value=10.0, label="10",
        updated_at=t0 + timedelta(days=1),
    )

    stub(monkeypatch, [a_recording()])
    mb.resolve_pending(session)

    winner = next(w for w in session.scalars(select(Work)) if w.merged_into is None)
    counted = session.scalar(
        select(func.count()).select_from(Rating).where(Rating.work_id == winner.id)
    )
    assert winner.rating_count == counted == 2
    assert winner.average == 8.0  # (10 + 6) / 2


def test_works_that_resolve_differently_stay_apart(session, users, monkeypatch):
    upsert_rating(session, users[0], *SONG, value=9.0, label="9")
    upsert_rating(session, users[1], "Nine Inch Nails", "The Downward Spiral", "Hurt",
                  value=8.0, label="8")

    seen = []

    def fake(method, url, **kwargs):
        class Response:
            status_code = 404

            def raise_for_status(self):
                pass

            def json(self):
                seen.append(url)
                return {"recordings": [a_recording(rid=f"rec-{len(seen)}")]}

        return Response()

    monkeypatch.setattr(mb, "_throttled", fake)
    mb.resolve_pending(session)

    assert len([w for w in session.scalars(select(Work)) if w.merged_into is None]) == 2


# ---------------------------------------------------------------- endpoint ----


def test_the_drain_endpoint_hides_from_the_unauthorized(client, monkeypatch):
    monkeypatch.setenv("RESOLVER_TOKEN", "sekrit")

    assert client.post("/v1/internal/resolve").status_code == 404
    assert client.post(
        "/v1/internal/resolve", headers={"Authorization": "Bearer wrong"}
    ).status_code == 404


def test_the_drain_endpoint_is_closed_when_no_token_is_configured(client, monkeypatch):
    """An unset secret must mean 'nobody', not 'everybody'."""
    monkeypatch.delenv("RESOLVER_TOKEN", raising=False)
    assert client.post(
        "/v1/internal/resolve", headers={"Authorization": "Bearer "}
    ).status_code == 404


def test_the_drain_endpoint_runs_for_the_holder_of_the_token(client, monkeypatch):
    monkeypatch.setenv("RESOLVER_TOKEN", "sekrit")
    monkeypatch.setattr(mb, "resolve_pending", lambda session, limit: {"attempted": 0, "resolved": 0})

    r = client.post("/v1/internal/resolve", headers={"Authorization": "Bearer sekrit"})

    assert r.status_code == 200 and r.get_json()["ok"] is True
