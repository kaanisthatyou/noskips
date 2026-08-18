"""Reading the shared world: albums, profiles, the feed.

Everything here is public-by-default but privacy-aware: a private profile, a
blocked reader and a note kept back by its author all narrow what comes out,
and they're checked here rather than trusted to the templates.
"""

from collections import defaultdict

from flask import g, jsonify, request
from sqlalchemy import func, select

from .. import listening
from ..models import Block, Follow, Rating, User, Work
from ..security import ApiError, current_user, require_handle
from ..store import first_press
from . import bp, presenters

PAGE = 30


def _wanted_limit(default=PAGE, ceiling=PAGE * 2):
    """?limit= from the query string, clamped. A junk value is a typo in a URL,
    not a reason to hand somebody a 500."""
    try:
        wanted = int(request.args.get("limit", default) or default)
    except ValueError:
        wanted = default
    return max(1, min(ceiling, wanted))


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
    stats = _stats(user) if visible else {}
    if visible:
        heard = listening.listening_breakdown(g.db, user)
        stats["listened_ms"] = heard
        stats["badges"] = listening.badges(g.db, user, stats, listened_total=heard["all"])
    return jsonify(
        ok=True,
        profile=presenters.profile(user, stats, viewer=viewer, visible=visible),
    )


@bp.get("/leaderboard")
def leaderboard():
    """The boards as JSON, on the same two axes as the page.

    Values are raw — milliseconds and counts — so a caller can format them
    however it likes rather than parsing "4h 12m" back into a number.
    """
    kind = request.args.get("board", "time")
    if kind not in listening.BOARDS:
        raise ApiError("no such board", 404, "no_board")
    period = request.args.get("period", "week")
    if period not in listening.PERIODS:
        raise ApiError("no such period", 400, "bad_period")

    rows = listening.board(g.db, kind=kind, period=period, limit=_wanted_limit())
    return jsonify(
        ok=True,
        board=kind,
        period=period,
        rows=[
            {
                "rank": i,
                "handle": row["user"].handle,
                "display_name": row["user"].display_name or row["user"].handle,
                "avatar_seed": row["user"].avatar_seed,
                # milliseconds on the time board, a plain count on the other
                "value": row["value"],
            }
            for i, row in enumerate(rows, 1)
        ],
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
        .limit(_wanted_limit())
    ).all()
    return jsonify(
        ok=True,
        verdicts=[presenters.rating(r, viewer=g.user, include_work=True) for r in rows],
    )


# ----------------------------------------------------------------- search ----
# The front door. Without this you can only reach an album page if somebody
# hands you the link, which is a strange thing to ask of a social product.

SEARCH_LIMIT = 40
MIN_QUERY = 2


def search_works(db, needle, limit=SEARCH_LIMIT):
    """Works whose artist, album or title contains the folded query.

    Substring rather than prefix: people search for the half of the title they
    remember. ``autoescape`` matters — a query of ``%`` would otherwise match
    the entire index.
    """
    if len(needle) < MIN_QUERY:
        return []
    like = (
        Work.norm_title.contains(needle, autoescape=True)
        | Work.norm_artist.contains(needle, autoescape=True)
        | Work.norm_album.contains(needle, autoescape=True)
    )
    return db.scalars(
        select(Work)
        .where(like, Work.merged_into.is_(None), Work.rating_count > 0)
        .order_by(Work.rating_count.desc(), Work.norm_title)
        .limit(limit)
    ).all()


def search_people(db, needle, limit=12):
    """Handles and display names. Private shelves are still findable — that a
    person exists isn't the secret, what's on their shelf is."""
    if len(needle) < MIN_QUERY:
        return []
    return db.scalars(
        select(User)
        .where(
            User.handle_ci.is_not(None),
            User.deleted_at.is_(None),
            User.is_banned.is_(False),
            User.handle_ci.contains(needle, autoescape=True)
            | func.lower(User.display_name).contains(needle, autoescape=True),
        )
        .order_by(User.handle_ci)
        .limit(limit)
    ).all()


def group_albums(works):
    """Collapse matched works into the albums they sit on.

    An album page is what a searcher usually wants — matching four tracks off
    one record should offer the record, not four near-identical rows.
    """
    albums = {}
    for w in works:
        entry = albums.setdefault(
            w.album_key,
            {
                "album_key": w.album_key,
                "artist": w.display_artist,
                "album": w.display_album,
                "cover_url": None,
                "hits": [],
            },
        )
        entry["hits"].append(w)
        entry["cover_url"] = entry["cover_url"] or w.cover_url
    for entry in albums.values():
        rated = entry["hits"]
        entry["rated_tracks"] = len(rated)
        entry["average"] = round(sum(w.average for w in rated) / len(rated), 2)
    return sorted(albums.values(), key=lambda a: -a["rated_tracks"])


@bp.get("/search")
def search():
    from ..resolve import normalize_query

    raw = (request.args.get("q") or "").strip()
    needle = normalize_query(raw)
    if len(needle) < MIN_QUERY:
        return jsonify(ok=True, query=raw, works=[], albums=[], people=[])

    works = search_works(g.db, needle)
    return jsonify(
        ok=True,
        query=raw,
        works=[presenters.work(w) for w in works],
        albums=[
            {k: v for k, v in album.items() if k != "hits"} for album in group_albums(works)
        ],
        people=[presenters.user_brief(u) for u in search_people(g.db, needle)],
    )


# ----------------------------------------------------------------- recent ----


def recent_verdicts(db, limit=PAGE):
    """The last public verdicts from public shelves.

    The user join isn't decoration: a rating can be public while its author's
    whole shelf is private, and that combination must not leak into a list
    anybody can read.
    """
    return db.scalars(
        select(Rating)
        .join(Work)
        .join(User, Rating.user_id == User.id)
        .where(
            Rating.is_public.is_(True),
            User.is_private.is_(False),
            User.is_banned.is_(False),
            User.deleted_at.is_(None),
            User.handle_ci.is_not(None),
        )
        .order_by(Rating.rated_at.desc())
        .limit(limit)
    ).all()


@bp.get("/recent")
def recent():
    limit = _wanted_limit()
    rows = recent_verdicts(g.db, limit)
    return jsonify(
        ok=True,
        verdicts=[
            presenters.rating(r, viewer=current_user(g.db), include_work=True) for r in rows
        ],
    )
