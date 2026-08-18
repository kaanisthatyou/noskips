"""The pages a human looks at.

Same palette, same fonts, same wobbly borders as the widget — the web half has
to read as the same object, not as a marketing site that happens to share a
name. It serves the widget's own `static/` folder for exactly that reason.
"""

import hashlib

from flask import Blueprint, g

from ..security import current_user

bp = Blueprint("web", __name__, template_folder="templates")

# Muted inks rather than random RGB — a hashed #7f3cd1 would look like a
# different product. Avatars are generated from a seed so there are no uploads,
# which means no image moderation and no storage bill.
_AVATAR_INKS = [
    "#cf4520", "#2f6f66", "#b5324f", "#6a4c93", "#2470a0",
    "#d9762b", "#4fb3a3", "#857c66", "#2f8f6f", "#e0654a",
]


@bp.app_template_global()
def avatar_style(seed, size=74):
    digest = hashlib.md5((seed or "noskips").encode("utf-8")).hexdigest()
    picks = [_AVATAR_INKS[int(digest[i : i + 2], 16) % len(_AVATAR_INKS)] for i in (0, 2, 4)]
    angle = int(digest[6:8], 16)
    return (
        f"width:{size}px;height:{size}px;"
        f"background:conic-gradient(from {angle}deg,"
        f"{picks[0]} 0 33%,{picks[1]} 33% 66%,{picks[2]} 66% 100%)"
    )


@bp.app_template_filter()
def score(value):
    """One decimal place, always — 8 and 8.0 shouldn't look like different
    kinds of number next to each other."""
    return "–" if value is None else f"{round(float(value) * 10) / 10:.1f}"


@bp.app_template_filter()
def listened(ms):
    """Milliseconds as a stretch of time a person would say out loud."""
    from ..listening import humanize_ms

    return humanize_ms(ms)


@bp.app_template_filter()
def ordinal(n):
    """The suffix only — templates print the number themselves.

    The teens are the whole reason this exists: 11th, 12th and 13th do not
    follow the rule the last digit would give them.
    """
    n = int(n or 0)
    if 11 <= (n % 100) <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


@bp.app_template_filter()
def day(dt):
    return dt.strftime("%d %b %Y").lower() if dt else ""


@bp.app_template_filter()
def trace_points(encoded):
    """A stored trace as SVG polyline points.

    The widget records 240 amplitude samples across a track and freezes them
    when a verdict is stamped, so this line is the actual shape of what was
    playing at that moment. Nothing else on the page can be faked less easily.
    """
    import sys
    from pathlib import Path

    # audio.py lives with the widget at the repo root, not in the server package
    root = str(Path(__file__).resolve().parent.parent.parent)
    if root not in sys.path:
        sys.path.insert(0, root)
    from audio import trace_to_points

    return trace_to_points(encoded)


@bp.app_template_global()
def discord_name(user):
    """The Discord handle behind an account, if it signed in that way.

    Only Discord: Google has no public @name to point at, and printing somebody
    else's gmail address on a public page would be a different thing entirely.
    Returns None when there's nothing to show, so the template renders nothing
    rather than an empty mark floating beside the handle.
    """
    for identity in user.identities:
        if identity.provider == "discord" and identity.username_at_provider:
            return identity.username_at_provider
    return None


_CAA_PREFIX = "https://coverartarchive.org/release-group/"
_CAA_SUFFIX = "/front-500"


@bp.app_template_global()
def art_src(cover_url):
    """A stored cover URL, pointed at our own cache-headed copy.

    Cover Art Archive answers a front-500 with two redirects and no
    Cache-Control at all, so a browser re-walks the whole chain on every load
    and a shelf of sixty costs 180 requests. Routing through /art gives the
    same bytes with a year of immutable on them. See web/art.py.

    Anything that isn't a CAA release-group URL is handed back untouched, so
    this can never turn a working image into a 404.
    """
    if not cover_url:
        return None
    if cover_url.startswith(_CAA_PREFIX) and cover_url.endswith(_CAA_SUFFIX):
        mbid = cover_url[len(_CAA_PREFIX):-len(_CAA_SUFFIX)]
        if "/" not in mbid:
            return f"/art/{mbid}/front.jpg"
    return cover_url


@bp.app_template_global()
def github_repo():
    """The repo the footer and download links point at. One definition, because
    it changes when the project is renamed."""
    from .releases import REPO

    return REPO


@bp.app_context_processor
def inject_me():
    """`me` is available in every template — the topbar needs it on all of them
    and threading it through each render call is how one page ends up
    mysteriously logged out."""
    return {"me": current_user(g.db) if "db" in g else None}


from . import admin, art, og, pages, pair_routes, releases  # noqa: E402,F401


@bp.app_template_global()
def og_image(path):
    """The absolute URL of a link-preview card, or None when card rendering
    isn't available — templates omit the tag rather than point at a 404."""
    from flask import request

    return f"{request.url_root.rstrip('/')}{path}" if og.enabled() else None
