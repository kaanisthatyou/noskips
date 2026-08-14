"""Profiles, album pages, the feed.

These render server-side from the database rather than fetching the JSON API,
so a profile is a real HTML page — it works with no JavaScript, it's readable
by whatever scrapes a link preview, and it's cacheable. The privacy rules come
from the same helpers the API uses, so there's one definition of who may read
what rather than two that drift.
"""

from flask import abort, g, redirect, render_template, request
from sqlalchemy import func, select

from ..api.read_api import _can_read, _find_user, _stats
from ..models import Follow, Rating, Work
from ..security import ApiError, current_user
from ..store import first_press
from . import bp

SHELF_LIMIT = 60


def _verdict_rows(user, viewer, limit=SHELF_LIMIT):
    query = select(Rating).join(Work).where(Rating.user_id == user.id)
    if not (viewer is not None and viewer.id == user.id):
        query = query.where(Rating.is_public.is_(True))
    return g.db.scalars(query.order_by(Rating.rated_at.desc()).limit(limit)).all()


@bp.get("/")
def index():
    """A placeholder, deliberately. The real landing page is the marketing site,
    which is planned but not built — see docs/WEBSITE.md."""
    me = current_user(g.db)
    if me and me.handle:
        return redirect(f"/@{me.handle}")
    if me:
        return redirect("/welcome")
    return render_template("index.html")


# ---------------------------------------------------------------- profile ----


@bp.get("/@<handle>")
def profile(handle):
    try:
        user = _find_user(handle)
    except ApiError:
        abort(404)

    viewer = current_user(g.db)
    if not _can_read(user, viewer):
        return render_template("profile.html", who=user, private=True, stats=None, verdicts=[])

    following = False
    if viewer is not None and viewer.id != user.id:
        following = g.db.scalar(
            select(func.count())
            .select_from(Follow)
            .where(Follow.follower_id == viewer.id, Follow.followee_id == user.id)
        ) > 0

    return render_template(
        "profile.html",
        who=user,
        private=False,
        stats=_stats(user),
        verdicts=_verdict_rows(user, viewer),
        following=following,
    )


# ------------------------------------------------------------------ album ----


@bp.get("/album/<album_key>")
def album(album_key):
    works = g.db.scalars(
        select(Work).where(Work.album_key == album_key, Work.merged_into.is_(None))
    ).all()
    rated = [w for w in works if w.rating_count]
    if not rated:
        # the rule, as a page: nobody has stamped this, so there is no page
        abort(404)

    average = round(sum(w.average for w in rated) / len(rated), 2)
    histogram = {n: 0 for n in range(1, 11)}
    for value in g.db.scalars(
        select(Rating.value).where(
            Rating.work_id.in_([w.id for w in rated]), Rating.is_public.is_(True)
        )
    ):
        histogram[max(1, min(10, round(float(value))))] += 1
    tallest = max(histogram.values()) or 1

    verdicts = g.db.scalars(
        select(Rating)
        .where(Rating.work_id.in_([w.id for w in rated]), Rating.is_public.is_(True))
        .order_by(Rating.rated_at.desc())
        .limit(40)
    ).all()

    return render_template(
        "album.html",
        works=sorted(rated, key=lambda w: (-(w.average or 0), w.display_title)),
        artist=rated[0].display_artist,
        title=rated[0].display_album,
        cover=next((w.cover_url for w in rated if w.cover_url), None),
        average=average,
        # a bar that has to earn the badge: high *and* more than a couple of tracks
        certified=average >= 9 and len(rated) >= 4,
        histogram=[(n, histogram[n], round(histogram[n] * 100 / tallest)) for n in range(1, 11)],
        verdicts=verdicts,
        viewer=current_user(g.db),
        first_press=first_press,
    )


# ------------------------------------------------------------------- feed ----


@bp.get("/feed")
def feed():
    me = current_user(g.db)
    if me is None:
        return redirect("/login?next=/feed")
    if not me.handle:
        return redirect("/welcome")

    followees = select(Follow.followee_id).where(Follow.follower_id == me.id)
    rows = g.db.scalars(
        select(Rating)
        .join(Work)
        .where(Rating.user_id.in_(followees), Rating.is_public.is_(True))
        .order_by(Rating.rated_at.desc())
        .limit(50)
    ).all()
    return render_template("feed.html", verdicts=rows, viewer=me)


# ----------------------------------------------------- account-shaped pages ----
# These are thin: the forms talk to the same /v1 endpoints the widget does, so
# there is exactly one implementation of signing up and one of claiming a name.


@bp.get("/login")
def login_page():
    if current_user(g.db):
        return redirect(request.args.get("next") or "/")
    return render_template("login.html", mode="login", next_url=request.args.get("next") or "/")


@bp.get("/signup")
def signup_page():
    if current_user(g.db):
        return redirect(request.args.get("next") or "/")
    return render_template("login.html", mode="signup", next_url=request.args.get("next") or "/")


@bp.get("/welcome")
def welcome():
    me = current_user(g.db)
    if me is None:
        return redirect("/login?next=/welcome")
    if me.handle:
        return redirect(f"/@{me.handle}")
    return render_template("welcome.html", next_url=request.args.get("next") or "")


@bp.get("/verify")
def verify_page():
    return render_template("token.html", purpose="verify", token=request.args.get("token", ""))


@bp.get("/reset")
def reset_page():
    return render_template("token.html", purpose="reset", token=request.args.get("token", ""))


@bp.get("/settings")
def settings():
    me = current_user(g.db)
    if me is None:
        return redirect("/login?next=/settings")
    devices = [d for d in me.devices if d.revoked_at is None]
    return render_template("settings.html", devices=devices)


@bp.get("/discord")
def discord():
    """A permanent address for the invite, so the invite itself can rotate
    without every link anyone has ever posted going dead."""
    import os

    return redirect(os.environ.get("DISCORD_INVITE", "https://discord.gg/"))


@bp.app_errorhandler(404)
def not_found(_exc):
    return render_template("notfound.html"), 404
