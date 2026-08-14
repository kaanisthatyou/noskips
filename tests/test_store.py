"""Tests for the one rule: nothing exists in the shared world until somebody
rates it, and it stops existing when the last person takes their verdict back.
"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import func, select

from server.models import Work
from server.store import (
    ConflictSkipped,
    delete_rating,
    first_press,
    get_work,
    upsert_rating,
)

SONG = ("Tame Impala", "Currents", "Let It Happen")
# the same song as another tagger would report it
SONG_VARIANT = ("Tame Impala", "Currents (Deluxe)", "Let It Happen - 2015 Remaster")


def work_count(session):
    return session.scalar(select(func.count()).select_from(Work))


# ------------------------------------------------------- nothing until rated ----


def test_unrated_song_has_no_entry(session):
    from server.resolve import work_key

    assert get_work(session, work_key(SONG[0], SONG[2])) is None
    assert work_count(session) == 0


def test_first_rating_creates_the_work(session, users):
    rating, created = upsert_rating(session, users[0], *SONG, value=8.0, label="8")

    assert created is True
    assert work_count(session) == 1
    assert rating.work.rating_count == 1
    assert rating.work.average == 8.0


def test_second_rater_does_not_create_a_second_work(session, users):
    upsert_rating(session, users[0], *SONG, value=8.0, label="8")
    _, created = upsert_rating(session, users[1], *SONG, value=6.0, label="6")

    assert created is False
    assert work_count(session) == 1


def test_variant_tags_land_on_the_same_work(session, users):
    """The whole point of resolve.py, exercised through the store."""
    upsert_rating(session, users[0], *SONG, value=9.0, label="9")
    upsert_rating(session, users[1], *SONG_VARIANT, value=7.0, label="7")

    assert work_count(session) == 1
    work = get_work(session, session.scalar(select(Work.work_key)))
    assert work.rating_count == 2
    assert work.average == 8.0


def test_last_rating_removed_deletes_the_work(session, users):
    upsert_rating(session, users[0], *SONG, value=8.0, label="8")
    assert delete_rating(session, users[0], *SONG) is True

    assert work_count(session) == 0


def test_work_survives_while_anyone_still_stands_behind_it(session, users):
    upsert_rating(session, users[0], *SONG, value=8.0, label="8")
    upsert_rating(session, users[1], *SONG, value=4.0, label="4")

    delete_rating(session, users[0], *SONG)

    assert work_count(session) == 1
    work = session.scalar(select(Work))
    assert work.rating_count == 1
    assert work.average == 4.0


def test_deleting_a_rating_that_was_never_made_is_a_no_op(session, users):
    upsert_rating(session, users[0], *SONG, value=8.0, label="8")
    assert delete_rating(session, users[1], *SONG) is False
    assert work_count(session) == 1


# ------------------------------------------------------------- first press ----


def test_first_press_is_the_earliest_rater(session, users):
    t0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
    upsert_rating(session, users[0], *SONG, value=8.0, label="8", rated_at=t0)
    upsert_rating(
        session, users[1], *SONG, value=6.0, label="6", rated_at=t0 + timedelta(hours=1)
    )

    work = session.scalar(select(Work))
    assert first_press(session, work).handle == "kaan"


def test_first_press_passes_on_when_the_first_rater_withdraws(session, users):
    t0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
    upsert_rating(session, users[0], *SONG, value=8.0, label="8", rated_at=t0)
    upsert_rating(
        session, users[1], *SONG, value=6.0, label="6", rated_at=t0 + timedelta(hours=1)
    )

    delete_rating(session, users[0], *SONG)

    work = session.scalar(select(Work))
    assert first_press(session, work).handle == "mert"


# ------------------------------------------------------------- re-stamping ----


def test_restamping_updates_in_place(session, users):
    upsert_rating(session, users[0], *SONG, value=8.0, label="8", rev=1)
    rating, created = upsert_rating(session, users[0], *SONG, value=3.0, label="3", rev=2)

    assert created is False
    assert work_count(session) == 1
    assert rating.work.rating_count == 1
    assert rating.work.average == 3.0


def test_average_is_correct_after_a_mix_of_edits(session, users):
    upsert_rating(session, users[0], *SONG, value=10.0, label="10", rev=1)
    upsert_rating(session, users[1], *SONG, value=5.0, label="5", rev=1)
    upsert_rating(session, users[0], *SONG, value=4.0, label="4", rev=2)

    work = session.scalar(select(Work))
    assert work.rating_count == 2
    assert work.average == 4.5


# --------------------------------------------------------------- sync races ----


def test_a_stale_replay_cannot_clobber_a_newer_verdict(session, users):
    """The widget retries its outbox, so the same op can arrive twice — and an
    op from an older revision must lose."""
    upsert_rating(session, users[0], *SONG, value=9.0, label="9", rev=5)

    with pytest.raises(ConflictSkipped):
        upsert_rating(session, users[0], *SONG, value=1.0, label="1", rev=4)

    work = session.scalar(select(Work))
    assert work.average == 9.0


def test_same_revision_resolves_by_timestamp(session, users):
    t0 = datetime(2026, 8, 1, tzinfo=timezone.utc)
    upsert_rating(session, users[0], *SONG, value=9.0, label="9", rev=1, updated_at=t0)

    with pytest.raises(ConflictSkipped):
        upsert_rating(
            session,
            users[0],
            *SONG,
            value=1.0,
            label="1",
            rev=1,
            updated_at=t0 - timedelta(minutes=5),
        )

    assert session.scalar(select(Work)).average == 9.0


# ------------------------------------------------------------------ details ----


def test_provenance_and_trace_are_stored(session, users):
    rating, _ = upsert_rating(
        session, users[0], *SONG, value=8.0, label="8", provenance="live", trace="AAEC"
    )
    assert rating.provenance == "live"
    assert rating.trace == "AAEC"


def test_display_strings_keep_the_first_seen_casing(session, users):
    upsert_rating(session, users[0], *SONG, value=8.0, label="8")
    upsert_rating(session, users[1], "tame impala", "currents", "let it happen", value=8.0, label="8")

    work = session.scalar(select(Work))
    assert work.display_artist == "Tame Impala"
    assert work.norm_artist == "tame impala"


def test_a_note_can_be_kept_private_while_the_number_is_public(session, users):
    rating, _ = upsert_rating(
        session, users[0], *SONG, value=8.0, label="8", note="too long", note_public=False
    )
    assert rating.is_public is True
    assert rating.note_public is False
    assert rating.note == "too long"
