"""Profiles, album pages, the feed.

These render server-side from the database rather than fetching the JSON API,
so a profile is a real HTML page — it works with no JavaScript, it's readable
by whatever scrapes a link preview, and it's cacheable. The privacy rules come
from the same helpers the API uses, so there's one definition of who may read
what rather than two that drift.
"""

from datetime import timedelta

from flask import (
    abort,
    current_app,
    g,
    make_response,
    redirect,
    render_template,
    request,
)
from sqlalchemy import func, select

from ..api.read_api import (
    _can_read,
    _find_user,
    MIN_QUERY,
    _stats,
    group_albums,
    recent_verdicts,
    search_people,
    search_works,
)
from .. import listening
from ..models import Follow, Rating, Work, utcnow
from ..resolve import normalize_query
from ..security import ApiError, current_user
from ..store import first_press
from . import bp, releases

SHELF_LIMIT = 60
RECENT_LIMIT = 40

# Below this the ticker looks abandoned rather than alive, so the landing page
# hides the section entirely instead of showing three lonely rows.
TICKER_FLOOR = 25


def _verdict_rows(user, viewer, limit=SHELF_LIMIT):
    query = select(Rating).join(Work).where(Rating.user_id == user.id)
    if not (viewer is not None and viewer.id == user.id):
        query = query.where(Rating.is_public.is_(True))
    return g.db.scalars(query.order_by(Rating.rated_at.desc()).limit(limit)).all()


@bp.get("/")
def index():
    """The landing page — for strangers.

    Somebody already signed in has a shelf, and that's their home; the front
    page exists to explain the one rule and hand out the exe. Both of those
    stay reachable afterwards at /download, so the redirect costs a signed-in
    reader nothing.
    """
    me = current_user(g.db)
    if me and me.handle:
        return redirect(f"/@{me.handle}")
    if me:
        return redirect("/welcome")

    total, ticker = _ticker()
    page = render_template(
        "index.html", ticker=ticker, total=total, downloads=releases.latest()
    )
    # a stranger's front page is the same bytes for everybody, so let a CDN
    # hold it and the database never sees most of this traffic
    response = make_response(page)
    response.headers["Cache-Control"] = "public, max-age=120"
    return response


# The ticker is the only thing on the landing page that touches Postgres, and
# the page is the most-hit URL on the site — so it's held for a couple of
# minutes. Per-process, which on serverless means it helps a warm instance and
# does nothing for a cold one; that's the honest ceiling without adding Redis,
# and the Cache-Control header above is what actually carries the load.
_TICKER_TTL = timedelta(minutes=2)


def _ticker():
    """The last public verdicts, and how many exist at all.

    The count is what decides whether the section appears: three lonely rows
    read as abandoned, and an empty ticker is worse than no ticker.

    The cache hangs off the app rather than the module so that two apps in one
    process — which is every test run — never read each other's world.
    """
    cache = current_app.extensions.setdefault(
        "ticker_cache", {"at": None, "total": 0, "html": ""}
    )
    now = utcnow()
    if cache["at"] is not None and now - cache["at"] < _TICKER_TTL:
        return cache["total"], cache["html"]

    total = g.db.scalar(
        select(func.count()).select_from(Rating).where(Rating.is_public.is_(True))
    )
    html = ""
    if total >= TICKER_FLOOR:
        html = render_template("_ticker.html", verdicts=recent_verdicts(g.db, 20))
    cache.update(at=now, total=total, html=html)
    return total, html


@bp.get("/download")
def download():
    """A permanent home for the artifacts, so a signed-in reader — who never
    sees the landing page — can still get the widget."""
    return render_template("download.html", downloads=releases.latest())


@bp.get("/privacy")
def privacy():
    return render_template("privacy.html")


# ----------------------------------------------------------------- finding ----


@bp.get("/search")
def search():
    raw = (request.args.get("q") or "").strip()
    needle = normalize_query(raw)
    works = search_works(g.db, needle)
    return render_template(
        "search.html",
        q=raw,
        albums=group_albums(works),
        people=search_people(g.db, needle),
        # a one-letter query isn't a search, and saying "nothing here yet"
        # about one nobody ran is a small lie about the state of the world
        searched=len(needle) >= MIN_QUERY,
    )


@bp.get("/stamp")
def stamp():
    """Judge something from the web.

    The widget catches a verdict at the second you had it, which is the better
    version of this; but a shelf you can only add to from one Windows machine
    isn't a shelf everyone can keep. Ratings from here are marked ``web`` and
    say so on the card, so the distinction survives.
    """
    me = current_user(g.db)
    if me is None:
        return redirect("/login?next=/stamp")
    if not me.handle:
        return redirect("/welcome")
    return render_template(
        "stamp.html",
        artist=request.args.get("artist", ""),
        album=request.args.get("album", ""),
        title=request.args.get("title", ""),
    )


@bp.get("/recent")
def recent():
    """Everything anyone has stamped, newest first.

    No ranking and no personalisation — the same list for everybody, which is
    the only kind of front page this product can honestly have.
    """
    return render_template("recent.html", verdicts=recent_verdicts(g.db, RECENT_LIMIT))


# ---------------------------------------------------------------- profile ----


@bp.get("/@<handle>")
def profile(handle):
    try:
        user = _find_user(handle)
    except ApiError:
        abort(404)

    viewer = current_user(g.db)
    if not _can_read(user, viewer):
        return render_template(
            "profile.html", who=user, private=True, stats=None,
            heard=None, badges=None, verdicts=[],
        )

    following = False
    if viewer is not None and viewer.id != user.id:
        following = g.db.scalar(
            select(func.count())
            .select_from(Follow)
            .where(Follow.follower_id == viewer.id, Follow.followee_id == user.id)
        ) > 0

    stats = _stats(user)
    heard = listening.listening_breakdown(g.db, user)
    return render_template(
        "profile.html",
        who=user,
        private=False,
        stats=stats,
        heard=heard,
        badges=listening.badges(g.db, user, stats, listened_total=heard["all"]),
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

    # the reader's own verdicts, so a track they've already judged offers to
    # change the number rather than pretending it's untouched
    viewer = current_user(g.db)
    yours = {}
    if viewer is not None:
        yours = {
            r.work_id: r
            for r in g.db.scalars(
                select(Rating).where(
                    Rating.user_id == viewer.id, Rating.work_id.in_([w.id for w in rated])
                )
            )
        }

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
        viewer=viewer,
        yours=yours,
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


BOARD_TITLES = {
    "time": ("time listened", "hours actually spent with the music"),
    "stamps": ("stamps", "verdicts stamped and stood behind"),
}
PERIOD_LABELS = {"day": "today", "week": "this week", "month": "this month", "all": "all time"}


@bp.get("/leaderboard")
def leaderboard():
    """Two boards, because there are two ways to be here: the people who listen
    and the people who commit to an opinion about what they listened to."""
    kind = request.args.get("board", "time")
    if kind not in listening.BOARDS:
        kind = "time"
    period = request.args.get("period", "week")
    if period not in listening.PERIODS:
        period = "week"

    rows = listening.board(g.db, kind=kind, period=period, limit=50)
    me = current_user(g.db)
    return render_template(
        "leaderboard.html",
        kind=kind,
        period=period,
        rows=rows,
        title=BOARD_TITLES[kind][0],
        blurb=BOARD_TITLES[kind][1],
        board_titles=BOARD_TITLES,
        period_labels=PERIOD_LABELS,
        # so somebody can find themselves in a list of fifty
        mine=next((i for i, r in enumerate(rows, 1) if me and r["user"].id == me.id), None),
    )


@bp.get("/discord")
def discord():
    """A permanent address for the invite, so the invite itself can rotate
    without every link anyone has ever posted going dead."""
    import os

    # `or`: a copied .env sets this to "", and redirect("") is a redirect to
    # the current page — an invite link that quietly loops. See server/db.py.
    return redirect(os.environ.get("DISCORD_INVITE") or "https://discord.gg/")


@bp.app_errorhandler(404)
def not_found(_exc):
    return render_template("notfound.html"), 404
