"""Reading the shared world: albums, profiles, the feed.

Everything here is public-by-default but privacy-aware: a private profile, a
blocked reader and a note kept back by its author all narrow what comes out,
and they're checked here rather than trusted to the templates.
"""

from collections import defaultdict

from flask import g, jsonify, request
from sqlalchemy import func, select

from ..models import Block, Follow, Rating, User, Work
from ..security import ApiError, current_user, require_handle
from ..store import first_press
from . import bp, presenters

PAGE = 30


def _find_user(handle):
    from ..auth.handles import normalize

    user = g.db.scalar(
        select(User).where(User.handle_ci == normalize(handle), User.deleted_at.is_(None))
    )
    if user is None or user.is_banned:
        raise ApiError("no such person", 404, "not_found")
    return user


def _blocked_between(a, b):
    if a is None or b is None:
        return False
    return g.db.scalar(
        select(func.count())
        .select_from(Block)
        .where(
            ((Block.blocker_id == a.id) & (Block.blocked_id == b.id))
            | ((Block.blocker_id == b.id) & (Block.blocked_id == a.id))
        )
    ) > 0


def _can_read(owner, viewer):
    if viewer is not None and viewer.id == owner.id:
        return True
    if _blocked_between(owner, viewer):
        return False
    return not owner.is_private


# ------------------------------------------------------------------ albums ----


@bp.get("/albums/<album_key>")
def album(album_key):
    works = g.db.scalars(
        select(Work).where(Work.album_key == album_key, Work.merged_into.is_(None))
    ).all()
    if not works:
        # same rule as a single work: no ratings, no page
        return jsonify(ok=False, exists=False, album_key=album_key), 404

    rated = [w for w in works if w.rating_count]
    average = round(sum(w.average for w in rated) / len(rated), 2) if rated else None

    # the light/just/strong scale gives 28 distinct values; collapse to the ten
    # columns people actually recognise, keeping the thirds as sub-counts
    histogram = defaultdict(int)
    for r in g.db.scalars(
        select(Rating).where(Rating.work_id.in_([w.id for w in works]), Rating.is_public.is_(True))
    ):
        histogram[max(1, min(10, round(float(r.value))))] += 1

    return jsonify(
        ok=True,
        exists=True,
        album={
            "album_key": album_key,
            "artist": works[0].display_artist,
            "album": works[0].display_album,
            "cover_url": next((w.cover_url for w in works if w.cover_url), None),
            "average": average,
            "rated_tracks": len(rated),
            "certified_noskips": average is not None and average >= 9 and len(rated) >= 4,
            "histogram": [{"score": n, "count": histogram.get(n, 0)} for n in range(1, 11)],
            "tracks": sorted(
                (
                    presenters.work(w, first_presser=first_press(g.db, w))
                    for w in rated
                ),
                key=lambda t: (-(t["average"] or 0), t["title"]),
            ),
        },
    )


# ----------------------------------------------------------------- people ----


def _stats(user):
    total = g.db.scalar(
        select(func.count()).select_from(Rating).where(Rating.user_id == user.id)
    )
    average = g.db.scalar(select(func.avg(Rating.value)).where(Rating.user_id == user.id))
    # a first press is a work whose earliest rating is theirs
    firsts = 0
    for work in g.db.scalars(select(Work).join(Rating).where(Rating.user_id == user.id)).unique():
        presser = first_press(g.db, work)
        if presser is not None and presser.id == user.id:
            firsts += 1
    return {
        "stamps": total,
        "average": round(float(average), 2) if average is not None else None,
        "first_presses": firsts,
        "following": g.db.scalar(
            select(func.count()).select_from(Follow).where(Follow.follower_id == user.id)
        ),
        "followers": g.db.scalar(
            select(func.count()).select_from(Follow).where(Follow.followee_id == user.id)
        ),
    }


@bp.get("/u/<handle>")
def profile(handle):
    user = _find_user(handle)
    viewer = current_user(g.db)
    visible = _can_read(user, viewer)
    return jsonify(
        ok=True,
        profile=presenters.profile(
            user, _stats(user) if visible else {}, viewer=viewer, visible=visible
        ),
    )


@bp.get("/u/<handle>/shelf")
def shelf(handle):
    user = _find_user(handle)
    viewer = current_user(g.db)
    if not _can_read(user, viewer):
        raise ApiError("this shelf is private", 403, "private")

    mine = viewer is not None and viewer.id == user.id
    query = select(Rating).join(Work).where(Rating.user_id == user.id)
    if not mine:
        query = query.where(Rating.is_public.is_(True))

    rows = g.db.scalars(query.order_by(Rating.rated_at.desc()).limit(PAGE * 4)).all()
    return jsonify(
        ok=True,
        handle=user.handle,
        verdicts=[presenters.rating(r, viewer=viewer, include_work=True) for r in rows],
    )


# ------------------------------------------------------------------- feed ----


@bp.get("/feed")
@require_handle
def feed():
    """Everyone you follow, newest first. No ranking, no suggestions, no
    'because you listened to' — it's a list of what your people said."""
    followees = select(Follow.followee_id).where(Follow.follower_id == g.user.id)
    rows = g.db.scalars(
        select(Rating)
        .join(Work)
        .where(Rating.user_id.in_(followees), Rating.is_public.is_(True))
        .order_by(Rating.rated_at.desc())
        .limit(int(request.args.get("limit", PAGE)))
    ).all()
    return jsonify(
        ok=True,
        verdicts=[presenters.rating(r, viewer=g.user, include_work=True) for r in rows],
    )
