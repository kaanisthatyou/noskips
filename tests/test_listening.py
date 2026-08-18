"""Time listened, the boards, and the badges.

The rules being pinned down here are the ones a person would try to cheat:
a rewind must not pay twice, a seek must not pay at all, and the bar for the
stamps board must not be visible anywhere a reader could find it.
"""

from datetime import timedelta

import pytest

from audio import Listen
from server import listening
from server.models import Cosign, User, utcnow
from server.store import upsert_rating


# ------------------------------------------------------------ the measurement ----


def _play(listen, key, duration, seconds):
    """Walk the playhead through a track the way the poller would."""
    for s in seconds:
        listen.feed(key, s, duration)


def test_straight_through_counts_the_whole_song():
    listen = Listen()
    _play(listen, "a:::b:::c", 100, range(0, 100))
    heard, coverage = listen.heard("a:::b:::c")
    assert heard == 100
    assert coverage == pytest.approx(1.0)


def test_a_rewind_does_not_pay_twice():
    """The point of the whole design: hearing the same 30s twice is 30s."""
    listen = Listen()
    _play(listen, "k", 100, range(0, 30))
    # ...and back to the start, again and again
    for _ in range(4):
        _play(listen, "k", 100, range(0, 30))

    heard, coverage = listen.heard("k")
    assert heard == 30, "five listens to the same half-minute is still half a minute"
    assert coverage == pytest.approx(0.30, abs=0.02)


def test_you_cannot_bank_more_than_the_song():
    listen = Listen()
    for _ in range(10):
        _play(listen, "k", 60, range(0, 60))
    heard, coverage = listen.heard("k")
    assert heard <= 61
    assert coverage <= 1.0


def test_skipping_ahead_is_not_listening():
    listen = Listen()
    _play(listen, "k", 300, range(0, 10))  # first ten seconds
    listen.feed("k", 290, 300)             # then jump to the end
    heard, _ = listen.heard("k")
    assert heard < 15, "a seek over the middle must not credit the middle"


def test_a_gap_small_enough_to_be_playback_is_filled_in():
    """Polls arrive late. A two-second gap is jitter, not a skip."""
    listen = Listen()
    listen.feed("k", 10, 200)
    listen.feed("k", 13, 200)
    heard, _ = listen.heard("k")
    assert heard == 4, "10,11,12,13 — the stretch actually played through"


def test_changing_track_starts_again():
    listen = Listen()
    _play(listen, "one", 100, range(0, 50))
    _play(listen, "two", 100, range(0, 5))
    assert listen.heard("one") == (0, 0.0), "the old track's listening is gone"
    heard, _ = listen.heard("two")
    assert heard == 5


def test_asking_for_a_different_track_gets_nothing():
    """Rating something from memory must not borrow what is playing now."""
    listen = Listen()
    _play(listen, "playing-now", 100, range(0, 90))
    assert listen.heard("some-other-song") == (0, 0.0)


def test_a_song_with_no_length_is_not_measured():
    listen = Listen()
    listen.feed("k", 10, 0)
    assert listen.heard("k") == (0, 0.0)


# ------------------------------------------------------------------ the store ----


def _rate(session, user, title, value=8, **kw):
    return upsert_rating(
        session, user, "artist", "album", title, value=value, label=str(value), **kw
    )[0]


def test_listening_is_stored_with_the_verdict(session, users):
    kaan = users[0]
    rating = _rate(session, kaan, "one", listened_ms=180_000, coverage=0.9)
    assert rating.listened_ms == 180_000
    assert float(rating.coverage) == pytest.approx(0.9)


def test_coverage_above_one_is_refused(session, users):
    rating = _rate(session, users[0], "one", listened_ms=999, coverage=4.2)
    assert float(rating.coverage) == 1.0


def test_a_restamp_keeps_the_best_sitting(session, users):
    """Skimming a track you once sat all the way through does not unhear it."""
    kaan = users[0]
    _rate(session, kaan, "one", value=9, listened_ms=200_000, coverage=0.95, rev=1)
    again = _rate(session, kaan, "one", value=4, listened_ms=5_000, coverage=0.02, rev=2)

    assert float(again.value) == 4, "the opinion is the new one"
    assert again.listened_ms == 200_000, "the listening is the best one"
    assert float(again.coverage) == pytest.approx(0.95)


# ------------------------------------------------------------------ the boards ----


def _shelf(session, user, count, coverage, listened_ms=60_000, when=None, tag="t"):
    """`tag` keeps two shelves for the same person on different songs — reuse a
    title and the second call restamps the first rating instead of adding one."""
    for i in range(count):
        r = _rate(
            session, user, f"{tag}{i}-{user.handle}",
            listened_ms=listened_ms, coverage=coverage,
        )
        if when is not None:
            r.rated_at = when
    session.flush()


def test_the_time_board_ranks_by_time(session, users):
    kaan, mert, asli = users
    _shelf(session, kaan, 2, 1.0, listened_ms=100_000)
    _shelf(session, mert, 5, 1.0, listened_ms=100_000)
    _shelf(session, asli, 1, 1.0, listened_ms=100_000)

    rows = listening.board_time(session, period="all")
    assert [r["user"].handle for r in rows] == ["mert", "kaan", "asli"]
    assert rows[0]["value"] == 500_000


def test_the_stamps_board_only_counts_a_song_properly_heard(session, users):
    """A shelf built from skips does not out-rank one built from listening."""
    kaan, mert, _ = users
    _shelf(session, kaan, 3, coverage=0.95)   # heard them
    _shelf(session, mert, 40, coverage=0.10)  # skipped through them

    rows = listening.board_stamps(session, period="all")
    handles = [r["user"].handle for r in rows]
    assert handles == ["kaan"], "forty skips is not forty stamps"
    assert rows[0]["value"] == 3


def test_the_bar_sits_just_where_it_is_meant_to(session, users):
    kaan, mert, asli = users
    _shelf(session, kaan, 1, coverage=0.81)
    _shelf(session, mert, 1, coverage=0.80)  # exactly on it, and over the line
    _shelf(session, asli, 1, coverage=0.79)

    counted = {r["user"].handle for r in listening.board_stamps(session, period="all")}
    assert counted == {"kaan", "mert"}


def test_a_private_shelf_is_not_on_the_boards(session, users):
    kaan, mert, _ = users
    kaan.is_private = True
    _shelf(session, kaan, 5, coverage=1.0)
    _shelf(session, mert, 1, coverage=1.0)
    session.flush()

    for board in (listening.board_time, listening.board_stamps):
        assert [r["user"].handle for r in board(session, period="all")] == ["mert"]


def test_banned_and_deleted_accounts_are_not_on_the_boards(session, users):
    kaan, mert, asli = users
    kaan.is_banned = True
    mert.deleted_at = utcnow()
    for u in (kaan, mert, asli):
        _shelf(session, u, 2, coverage=1.0)
    session.flush()

    assert [r["user"].handle for r in listening.board_time(session, period="all")] == ["asli"]


def test_the_windows_only_see_what_falls_inside_them(session, users):
    kaan = users[0]
    _shelf(session, kaan, 1, coverage=1.0, listened_ms=50_000, tag="fresh")
    _shelf(session, kaan, 1, coverage=1.0, listened_ms=90_000, tag="old",
           when=utcnow() - timedelta(days=10))

    assert listening.listening_ms(session, kaan, "day") == 50_000
    assert listening.listening_ms(session, kaan, "week") == 50_000
    assert listening.listening_ms(session, kaan, "month") == 140_000
    assert listening.listening_ms(session, kaan, "all") == 140_000


# ------------------------------------------------------------------ the badges ----


def test_badges_tier_up_as_the_shelf_grows(session, users):
    kaan = users[0]
    _shelf(session, kaan, 12, coverage=1.0)

    wall = {b["slug"]: b for b in listening.badges(session, kaan, {"stamps": 12})}
    shelf = wall["shelf"]
    assert shelf["tier"] == 2, "past 1 and past 10, not yet 50"
    assert shelf["mark"] == "ii"
    assert shelf["next"] == 50
    assert shelf["earned"] is True


def test_an_unearned_badge_still_comes_back(session, users):
    wall = {b["slug"]: b for b in listening.badges(session, users[0], {"stamps": 0})}
    assert wall["shelf"]["earned"] is False
    assert wall["shelf"]["tier"] == 0
    assert wall["shelf"]["mark"] == ""
    assert wall["shelf"]["progress"] == 0


def test_the_badges_count_what_they_say(session, users):
    kaan, mert, _ = users
    ten = _rate(session, kaan, "a perfect one", value=10)
    _rate(session, kaan, "a fine one", value=6)
    session.add(Cosign(user_id=mert.id, rating_id=ten.id))
    session.flush()

    wall = {b["slug"]: b for b in listening.badges(session, kaan, {"stamps": 2})}
    assert wall["tens"]["count"] == 1
    assert wall["cosigned"]["count"] == 1
    assert wall["net"]["count"] == 1, "both on the same artist"
    assert wall["regular"]["count"] == 1, "both stamped today"


def test_hours_in_reads_the_time_actually_listened(session, users):
    kaan = users[0]
    wall = {
        b["slug"]: b
        for b in listening.badges(
            session, kaan, {"stamps": 0}, listened_total=11 * 3_600_000
        )
    }
    assert wall["hours"]["count"] == 11
    assert wall["hours"]["tier"] == 2, "past one hour and past ten"


# ------------------------------------------------------------------- the pages ----


def test_the_board_page_renders(client):
    assert client.get("/leaderboard").status_code == 200
    assert client.get("/leaderboard?board=stamps&period=month").status_code == 200


def test_a_nonsense_board_falls_back_rather_than_500ing(client):
    r = client.get("/leaderboard?board=nonsense&period=nonsense")
    assert r.status_code == 200


def test_the_board_json_answers_with_raw_numbers(client, db):
    user = User(handle="kaan", handle_ci="kaan")
    db.add(user)
    db.flush()
    upsert_rating(
        db, user, "a", "b", "c", value=9, label="9",
        listened_ms=120_000, coverage=1.0,
    )
    db.commit()

    body = client.get("/v1/leaderboard?board=time&period=all").get_json()
    assert body["ok"] is True
    assert body["rows"][0]["handle"] == "kaan"
    assert body["rows"][0]["value"] == 120_000, "milliseconds, not '2m'"


def test_the_bar_for_the_stamps_board_is_never_stated(client, db):
    """The threshold is enforced, not advertised. If this fails, something has
    printed the rule onto a page — which is exactly what it must not do."""
    user = User(handle="kaan", handle_ci="kaan")
    db.add(user)
    db.flush()
    upsert_rating(db, user, "a", "b", "c", value=9, label="9",
                  listened_ms=1000, coverage=1.0)
    db.commit()

    pages = [
        client.get("/leaderboard?board=stamps").get_data(as_text=True),
        client.get("/leaderboard?board=time").get_data(as_text=True),
        client.get("/@kaan").get_data(as_text=True),
        client.get("/v1/leaderboard?board=stamps").get_data(as_text=True),
        client.get("/v1/u/kaan").get_data(as_text=True),
    ]
    for page in pages:
        lowered = page.lower()
        for tell in ("80%", "0.8", "80 percent", "coverage", "qualifying"):
            assert tell not in lowered, f"the bar leaked into a response: {tell!r}"
