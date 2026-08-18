"""What the numbers add up to: time listened, the boards, and the badges.

One module because all three read the same two columns and would otherwise
drift apart — a badge that disagrees with the board it sits under is worse than
either of them missing.

Two conventions worth knowing before reading the queries:

* **Windows are rolling, not calendar.** "this week" is the last seven days,
  not "since Monday". Calendar boundaries need a timezone per reader to mean
  anything, and there isn't one: the widget syncs from wherever it is and the
  site is read from everywhere. Rolling windows mean the same thing to
  everybody, which is the property a leaderboard actually needs.

* **Who is eligible is decided once**, in ``_listable``, and every board goes
  through it. A private shelf is not a leaderboard entry, and neither is a
  banned or deleted account.
"""

from datetime import timedelta

from sqlalchemy import String, cast, distinct, func, select

from .models import Cosign, Rating, User, Work, utcnow

# How much of a song has to have gone past for the verdict on it to count
# towards the stamps board. Deliberately not surfaced: no label, no tooltip and
# no API field quotes this number, and the board is called "stamps" because
# that is what it counts. Stated here once, used in one place, nowhere else.
_QUALIFYING_COVERAGE = 0.80

PERIODS = ("day", "week", "month", "all")
_WINDOWS = {
    "day": timedelta(days=1),
    "week": timedelta(days=7),
    "month": timedelta(days=30),
    "all": None,
}


def period_start(period):
    """The moment a window opens, or None for all time."""
    window = _WINDOWS.get(period)
    return utcnow() - window if window else None


def _in_period(query, period):
    start = period_start(period)
    return query.where(Rating.rated_at >= start) if start else query


def _listable(query):
    """Only accounts that belong on a public board."""
    return query.where(
        User.is_private.is_(False),
        User.is_banned.is_(False),
        User.deleted_at.is_(None),
        User.handle_ci.is_not(None),
    )


# --------------------------------------------------------------- one person ----


def listening_ms(db, user, period="all"):
    total = db.scalar(
        _in_period(
            select(func.sum(Rating.listened_ms)).where(Rating.user_id == user.id), period
        )
    )
    return int(total or 0)


def listening_breakdown(db, user):
    """Time listened across every window, for the profile."""
    return {period: listening_ms(db, user, period) for period in PERIODS}


def qualifying_stamps(db, user, period="all"):
    """Verdicts that count towards the board. See ``_QUALIFYING_COVERAGE``."""
    total = db.scalar(
        _in_period(
            select(func.count())
            .select_from(Rating)
            .where(Rating.user_id == user.id, Rating.coverage >= _QUALIFYING_COVERAGE),
            period,
        )
    )
    return int(total or 0)


# ---------------------------------------------------------------- the boards ----


def board_time(db, period="all", limit=25):
    """Who has spent the most time listening."""
    rows = db.execute(
        _listable(
            _in_period(
                select(User, func.sum(Rating.listened_ms).label("total")).join(
                    Rating, Rating.user_id == User.id
                ),
                period,
            )
        )
        .group_by(User.id)
        .having(func.sum(Rating.listened_ms) > 0)
        .order_by(func.sum(Rating.listened_ms).desc(), User.created_at.asc())
        .limit(limit)
    ).all()
    return [{"user": user, "value": int(total or 0)} for user, total in rows]


def board_stamps(db, period="all", limit=25):
    """Who has given the most verdicts.

    The bar a verdict has to clear is applied here, in the ``where``, and is
    never named in what this returns: callers get a count called "stamps".
    """
    rows = db.execute(
        _listable(
            _in_period(
                select(User, func.count(Rating.id).label("total"))
                .join(Rating, Rating.user_id == User.id)
                .where(Rating.coverage >= _QUALIFYING_COVERAGE),
                period,
            )
        )
        .group_by(User.id)
        .having(func.count(Rating.id) > 0)
        .order_by(func.count(Rating.id).desc(), User.created_at.asc())
        .limit(limit)
    ).all()
    return [{"user": user, "value": int(total or 0)} for user, total in rows]


BOARDS = {"time": board_time, "stamps": board_stamps}


def board(db, kind="time", period="all", limit=25):
    return BOARDS.get(kind, board_time)(db, period=period, limit=limit)


# ------------------------------------------------------------------- badges ----

# Each badge is (slug, title, what it measures, the line under it, thresholds).
# Thresholds ascend; how many you have cleared is your tier. Nothing here is
# stored — a badge is a reading of the shelf, so it can never disagree with it,
# and a withdrawn verdict takes its badge with it.
#
# Note what is absent: nothing here counts how *much* of a song was heard.
# A badge for that would put the boards' bar on a page with a number next to
# it, and that bar is meant to be felt rather than gamed.
BADGES = (
    ("shelf", "the shelf", "stamps", "verdicts stamped and stood behind",
     (1, 10, 50, 250, 1000)),
    ("press", "first press", "first_presses", "songs nobody here had rated before you",
     (1, 5, 25, 100)),
    ("hours", "hours in", "hours", "hours of music gone past",
     (1, 10, 50, 200)),
    ("net", "wide net", "artists", "different artists on the shelf",
     (5, 25, 100, 400)),
    ("tens", "top marks", "tens", "perfect tens handed out",
     (1, 10, 50)),
    ("cosigned", "cosigned", "cosigns", "times somebody countersigned you",
     (1, 10, 100)),
    ("regular", "the regular", "days", "days you turned up and judged something",
     (7, 30, 180)),
)

TIER_MARKS = ("i", "ii", "iii", "iv", "v")


def _measures(db, user):
    """Every number the badges read, in as few queries as they can be had."""
    tens = db.scalar(
        select(func.count())
        .select_from(Rating)
        .where(Rating.user_id == user.id, Rating.value >= 10)
    )
    artists = db.scalar(
        select(func.count(distinct(Work.norm_artist)))
        .select_from(Rating)
        .join(Work, Work.id == Rating.work_id)
        .where(Rating.user_id == user.id)
    )
    cosigns = db.scalar(
        select(func.count())
        .select_from(Cosign)
        .join(Rating, Rating.id == Cosign.rating_id)
        .where(Rating.user_id == user.id)
    )
    # Distinct calendar days, taken as the front of the timestamp rendered as
    # text. Both engines render one starting YYYY-MM-DD, which is more than
    # can be said for date(): SQLite's takes a string, Postgres's takes a
    # timestamp, and the cast that would unify them differs again per engine.
    days = db.scalar(
        select(
            func.count(distinct(func.substr(cast(Rating.rated_at, String), 1, 10)))
        ).where(Rating.user_id == user.id)
    )
    return {
        "tens": int(tens or 0),
        "artists": int(artists or 0),
        "cosigns": int(cosigns or 0),
        "days": int(days or 0),
    }


def badges(db, user, stats, listened_total=None):
    """Every badge, earned or not.

    Unearned ones come back too, with how far along they are: a wall with gaps
    in it is the reason to go and listen to something, and hiding the gaps
    makes the earned ones look like the whole set.
    """
    if listened_total is None:
        listened_total = listening_ms(db, user, "all")

    have = _measures(db, user)
    have["stamps"] = int(stats.get("stamps") or 0)
    have["first_presses"] = int(stats.get("first_presses") or 0)
    have["hours"] = listened_total // 3_600_000

    out = []
    for slug, title, measure, blurb, steps in BADGES:
        count = have.get(measure, 0)
        tier = sum(1 for step in steps if count >= step)
        nxt = steps[tier] if tier < len(steps) else None
        out.append(
            {
                "slug": slug,
                "title": title,
                "blurb": blurb,
                "count": count,
                "tier": tier,
                "mark": TIER_MARKS[tier - 1] if tier else "",
                "tiers": len(steps),
                "earned": tier > 0,
                "next": nxt,
                # how far into the tier being worked on, for the badge's ring
                "progress": min(1.0, count / nxt) if nxt else 1.0,
            }
        )
    return out


# ------------------------------------------------------------------ display ----


def humanize_ms(ms):
    """4h 12m, 12m, 0m — never 0.7 hours."""
    minutes = int(ms or 0) // 60_000
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes}m" if hours else f"{minutes}m"
