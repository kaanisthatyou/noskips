"""The one rule, in code.

    A song has no entry in the shared world until a human rates it.

Everything that can create or destroy a ``Work`` lives in this module, so the
rule is enforced in one readable place rather than scattered across handlers.
There is deliberately no ``create_work`` in the public surface: the only way a
work comes into existence is somebody stamping a verdict on it, and the only
way it survives is somebody still standing behind that verdict.
"""

from datetime import timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from .models import Rating, User, Work, utcnow
from .resolve import identify


class ConflictSkipped(Exception):
    """A sync op lost to a newer revision already on the server."""


# ------------------------------------------------------------------ lookup ----


def get_work(session, work_key, follow_merges=True):
    """The work for a key, or None if nobody has ever rated it.

    None is the honest answer to "what does the world think of this song?" when
    the world has never heard it. Callers turn it into a 404, never into an
    empty shell with a zero in it.
    """
    work = session.scalar(select(Work).where(Work.work_key == work_key))
    if work and follow_merges:
        seen = set()
        while work.merged_into and work.id not in seen:
            seen.add(work.id)
            work = session.get(Work, work.merged_into)
            if work is None:
                return None
    return work


def first_press(session, work):
    """Who got here first — derived, never stored.

    Deriving it means the credit stays honest: if the first rater deletes their
    verdict, it passes to whoever was actually next rather than pointing at
    someone who no longer stands behind it.
    """
    return session.scalar(
        select(User)
        .join(Rating, Rating.user_id == User.id)
        .where(Rating.work_id == work.id)
        .order_by(Rating.rated_at.asc(), Rating.id.asc())
        .limit(1)
    )


def _aware(dt):
    """SQLite hands back naive datetimes; compare like-for-like."""
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


# ------------------------------------------------------------------- write ----


def _get_or_create_work(session, ident, artist, album, title):
    """Fetch the work, or bring it into existence for its very first rating.

    Two people can rate the same never-before-rated song at the same instant, so
    losing the insert race is expected, not exceptional: fall back to a re-read.
    """
    work = get_work(session, ident.work_key)
    if work:
        return work

    work = Work(
        work_key=ident.work_key,
        album_key=ident.album_key,
        norm_artist=ident.artist,
        norm_album=ident.album,
        norm_title=ident.title,
        display_artist=artist,
        display_album=album,
        display_title=title,
        feat=list(ident.feat),
    )
    try:
        with session.begin_nested():
            session.add(work)
        return work
    except IntegrityError:
        # somebody else first-pressed it a millisecond ago — use theirs
        found = get_work(session, ident.work_key)
        if found is None:  # pragma: no cover — only on a genuinely broken DB
            raise
        return found


def upsert_rating(
    session,
    user,
    artist,
    album,
    title,
    value,
    label,
    note=None,
    trace=None,
    provenance="web",
    rev=1,
    rated_at=None,
    updated_at=None,
    is_public=True,
    note_public=True,
    device_id=None,
):
    """Store or replace this user's verdict on a song, creating the work if this
    is the first verdict anyone has ever stamped on it.

    Returns ``(rating, created_work)`` so callers can celebrate a first press.
    """
    ident = identify(artist, album, title)
    existing_work = get_work(session, ident.work_key)
    work = existing_work or _get_or_create_work(session, ident, artist, album, title)
    created_work = existing_work is None

    rating = session.scalar(
        select(Rating).where(Rating.user_id == user.id, Rating.work_id == work.id)
    )
    now = utcnow()
    value = round(float(value), 2)

    if rating is None:
        rating = Rating(
            user_id=user.id,
            work_id=work.id,
            value=value,
            label=label,
            note=note,
            trace=trace,
            provenance=provenance,
            rev=rev,
            is_public=is_public,
            note_public=note_public,
            device_id=device_id,
            rated_at=rated_at or now,
            updated_at=updated_at or now,
        )
        session.add(rating)
        work.rating_count += 1
        work.rating_sum = float(work.rating_sum) + value
    else:
        # last write wins, but a replayed or stale op must never clobber a newer
        # verdict — the widget retries its outbox and we want that to be safe
        incoming = _aware(updated_at) or now
        if rev < rating.rev or (rev == rating.rev and incoming < _aware(rating.updated_at)):
            raise ConflictSkipped(str(rating.id))
        work.rating_sum = float(work.rating_sum) - float(rating.value) + value
        rating.value = value
        rating.label = label
        rating.note = note
        rating.trace = trace or rating.trace
        rating.provenance = provenance
        rating.rev = rev
        rating.is_public = is_public
        rating.note_public = note_public
        rating.updated_at = incoming
        if device_id:
            rating.device_id = device_id

    session.flush()
    return rating, created_work


def delete_rating(session, user, artist, album, title):
    """Withdraw this user's verdict — and if it was the last one standing, take
    the song back out of the shared world entirely.

    This mirrors what the widget already does locally in ``api_unrate``: an
    album with no rated tracks left stops existing rather than lingering empty.
    """
    ident = identify(artist, album, title)
    work = get_work(session, ident.work_key)
    if work is None:
        return False

    rating = session.scalar(
        select(Rating).where(Rating.user_id == user.id, Rating.work_id == work.id)
    )
    if rating is None:
        return False

    work.rating_count -= 1
    work.rating_sum = float(work.rating_sum) - float(rating.value)
    session.delete(rating)
    session.flush()

    remaining = session.scalar(
        select(func.count()).select_from(Rating).where(Rating.work_id == work.id)
    )
    if not remaining:
        session.delete(work)  # nobody rated it, so it doesn't exist
    session.flush()
    return True
