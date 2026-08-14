"""Link preview cards, drawn rather than screenshotted.

When someone posts a profile or an album into Discord, the unfurl *is* the
product's first impression. So these are the real thing: paper colour, the real
Special Elite, the number stamped crooked, and (once Phase 4 lands) the trace
of the moment the verdict was stamped.

Pillow is imported softly. If it isn't available the pages simply omit their
og:image rather than 500 — a missing preview is a much smaller problem than a
dead profile page.
"""

import io
import os
from pathlib import Path

from flask import Response, abort, g, request
from sqlalchemy import select

from ..api.read_api import _can_read, _find_user, _stats
from ..models import Work
from ..security import ApiError, current_user
from . import bp

try:  # pragma: no cover - exercised by whether the tests skip
    from PIL import Image, ImageDraw, ImageFont

    AVAILABLE = True
except ImportError:  # pragma: no cover
    AVAILABLE = False

FONTS = Path(__file__).resolve().parent.parent.parent / "static" / "fonts"
W, H = 1200, 630

PAPER = (240, 233, 216)
CARD = (251, 246, 234)
INK = (36, 31, 23)
STAMP = (207, 69, 32)
SOFT = (133, 124, 102)
TEAL = (47, 111, 102)


def _font(name, size):
    try:
        return ImageFont.truetype(str(FONTS / name), size)
    except OSError:  # pragma: no cover - only if the fonts go missing
        return ImageFont.load_default()


def _fit(draw, text, font_name, size, max_width):
    """Shrink until it fits. Album titles vary wildly in length and a card that
    runs off its own edge looks broken in a way a slightly smaller one doesn't."""
    while size > 22:
        font = _font(font_name, size)
        if draw.textlength(text, font=font) <= max_width:
            return font
        size -= 4
    return _font(font_name, size)


def _canvas():
    """Paper, a torn-looking inner border, and the wordmark. Every card starts
    the same way so they're recognisable in a feed of other people's links."""
    image = Image.new("RGB", (W, H), PAPER)
    draw = ImageDraw.Draw(image)
    draw.rectangle([28, 28, W - 28, H - 28], fill=CARD, outline=INK, width=5)
    draw.text((64, 52), "noskips", font=_font("SpecialElite.ttf", 38), fill=INK)
    draw.text((64, 100), "judge every song. keep receipts.",
              font=_font("Caveat.ttf", 30), fill=SOFT)
    return image, draw


def _png(image):
    buffer = io.BytesIO()
    image.save(buffer, format="PNG", optimize=True)
    return Response(
        buffer.getvalue(),
        mimetype="image/png",
        headers={"Cache-Control": "public, max-age=3600"},
    )


@bp.get("/og/site.png")
def site_card():
    """The card for the front page itself, drawn by the same code as everything
    else so a link to the site sits alongside links to a shelf without looking
    like it came from a different product."""
    if not AVAILABLE:
        abort(404)
    image, draw = _canvas()
    draw.text((64, 230), "judge every", font=_font("SpecialElite.ttf", 96), fill=INK)
    draw.text((64, 340), "song.", font=_font("SpecialElite.ttf", 96), fill=STAMP)
    draw.text((64, 470), "no catalog. a song has no page here", font=_font("Caveat.ttf", 44), fill=SOFT)
    draw.text((64, 520), "until somebody rates it.", font=_font("Caveat.ttf", 44), fill=SOFT)
    return _png(image)


@bp.get("/og/u/<handle>.png")
def profile_card(handle):
    if not AVAILABLE:
        abort(404)
    try:
        user = _find_user(handle)
    except ApiError:
        abort(404)
    if not _can_read(user, current_user(g.db)):
        abort(404)

    stats = _stats(user)
    image, draw = _canvas()

    draw.text((64, 210), f"@{user.handle}", font=_font("SpecialElite.ttf", 88), fill=INK)
    if user.bio:
        draw.text((64, 320), user.bio[:70], font=_font("Caveat.ttf", 40), fill=SOFT)

    columns = [
        (str(stats["stamps"]), "STAMPS", INK),
        (f"{stats['average']:.1f}" if stats["average"] is not None else "–", "AVERAGE", INK),
        # the number worth bragging about
        (str(stats["first_presses"]), "FIRST PRESSES", STAMP),
    ]
    x = 64
    for value, label, colour in columns:
        draw.text((x, 420), value, font=_font("SpecialElite.ttf", 74), fill=colour)
        draw.text((x, 512), label, font=_font("SpecialElite.ttf", 24), fill=SOFT)
        x += 340

    return _png(image)


@bp.get("/og/album/<album_key>.png")
def album_card(album_key):
    if not AVAILABLE:
        abort(404)
    works = [
        w for w in g.db.scalars(select(Work).where(Work.album_key == album_key)).all()
        if w.rating_count
    ]
    if not works:
        abort(404)  # nobody rated it, so there's nothing to preview

    average = sum(w.average for w in works) / len(works)
    image, draw = _canvas()

    title = works[0].display_album or "(single)"
    draw.text((64, 210), title, font=_fit(draw, title, "SpecialElite.ttf", 76, 700), fill=INK)
    draw.text((64, 310), works[0].display_artist[:44],
              font=_font("SpecialElite.ttf", 40), fill=STAMP)
    draw.text((64, 430), f"{len(works)} rated tracks",
              font=_font("SpecialElite.ttf", 28), fill=SOFT)

    if average >= 9 and len(works) >= 4:
        draw.text((64, 480), "CERTIFIED NO-SKIPS", font=_font("SpecialElite.ttf", 34), fill=STAMP)

    # the average, stamped rather than printed
    draw.ellipse([880, 250, 1120, 470], outline=STAMP, width=6)
    big = _font("SpecialElite.ttf", 110)
    text = f"{round(average * 10) / 10:.1f}"
    draw.text((1000 - draw.textlength(text, font=big) / 2, 300), text, font=big, fill=STAMP)

    return _png(image)


def enabled():
    return AVAILABLE and not os.environ.get("NOSKIPS_NO_OG")
