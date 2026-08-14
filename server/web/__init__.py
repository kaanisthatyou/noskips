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


from . import admin, og, pages, pair_routes, releases  # noqa: E402,F401


@bp.app_template_global()
def og_image(path):
    """The absolute URL of a link-preview card, or None when card rendering
    isn't available — templates omit the tag rather than point at a 404."""
    from flask import request

    return f"{request.url_root.rstrip('/')}{path}" if og.enabled() else None
