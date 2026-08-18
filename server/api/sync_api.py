"""Taking the widget's outbox.

Ops arrive batched and possibly more than once — the widget retries whatever it
couldn't confirm, so every op here has to be safe to replay. Each one is
answered individually rather than failing the batch: one malformed op from an
old client version must not wedge somebody's entire queue forever.
"""

from datetime import datetime, timedelta, timezone

from flask import g, jsonify, request
from sqlalchemy import select

from ..models import Rating, Work
from ..security import ApiError, current_device, rate_limit, require_handle
from ..store import ConflictSkipped, delete_rating, first_press, get_work, upsert_rating
from . import bp, presenters

MAX_OPS = 200
MAX_NOTE = 2000
MAX_TRACE = 1024
# twelve hours against one track is not a song, it is a stuck clock
MAX_LISTENED_MS = 12 * 60 * 60 * 1000


def _dt(value):
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _clean_op(op):
    artist = (op.get("artist") or "").strip()
    title = (op.get("title") or "").strip()
    if not title:
        raise ApiError("a track needs a title", 400, "bad_op")
    return artist, (op.get("album") or "").strip(), title


@bp.post("/sync")
@require_handle
def sync():
    rate_limit(g.db, "sync", limit=60, per=timedelta(minutes=5), key=str(g.user.id))
    payload = request.get_json(silent=True) or {}
    ops = payload.get("ops") or []
    if not isinstance(ops, list):
        raise ApiError("ops must be a list", 400, "bad_payload")
    if len(ops) > MAX_OPS:
        raise ApiError(f"send at most {MAX_OPS} ops at a time", 400, "too_many_ops")

    device = current_device(g.db)
    results = []

    for op in ops:
        try:
            results.append(_apply(op, device))
        except ApiError as exc:
            # report and move on — a bad op must not block the rest of the queue
            results.append({"status": "rejected", "error": exc.message})

    return jsonify(ok=True, results=results)


def _apply(op, device):
    kind = op.get("op", "rate")
    artist, album, title = _clean_op(op)

    if kind == "unrate":
        removed = delete_rating(g.db, g.user, artist, album, title)
        return {"status": "deleted" if removed else "missing", "title": title}

    if kind != "rate":
        raise ApiError(f"unknown op {kind!r}", 400, "bad_op")

    try:
        value = float(op["value"])
    except (KeyError, TypeError, ValueError):
        raise ApiError("a rating needs a numeric value", 400, "bad_op")
    if not 0 < value <= 10:
        raise ApiError("ratings run from 1 to 10", 400, "bad_op")

    note = (op.get("note") or "").strip()[:MAX_NOTE] or None
    trace = (op.get("trace") or "")[:MAX_TRACE] or None

    # How much of the song went past, as measured by the widget. Only a paired
    # device can claim any: the web form has no playhead to watch, and letting
    # a bare POST assert its own listening would make the boards worthless.
    listened_ms, coverage = 0, 0.0
    if device is not None:
        try:
            listened_ms = max(0, min(int(op.get("listened_ms") or 0), MAX_LISTENED_MS))
            coverage = min(1.0, max(0.0, float(op.get("coverage") or 0.0)))
        except (TypeError, ValueError):
            listened_ms, coverage = 0, 0.0
    # only a paired widget may claim it was stamped live
    provenance = "live" if (op.get("provenance") == "live" and device is not None) else "web"

    try:
        rating, created_work = upsert_rating(
            g.db,
            g.user,
            artist,
            album,
            title,
            value=value,
            label=(op.get("label") or str(value))[:40],
            note=note,
            trace=trace,
            provenance=provenance,
            rev=int(op.get("rev") or 1),
            rated_at=_dt(op.get("rated_at")),
            updated_at=_dt(op.get("updated_at")),
            is_public=bool(op.get("is_public", True)),
            note_public=bool(op.get("note_public", not g.user.notes_private_default)),
            device_id=device.id if device else None,
            listened_ms=listened_ms,
            coverage=coverage,
        )
    except ConflictSkipped:
        # the server already holds a newer verdict; the widget should take ours
        return {"status": "skipped", "title": title}

    work = rating.work
    return {
        "status": "stored",
        "title": title,
        "work_key": work.work_key,
        # the web stamp form sends you to the record afterwards, and only the
        # server knows which one a freshly-normalized title landed on
        "album_key": work.album_key,
        "average": work.average,
        "count": work.rating_count,
        # the good moment: nobody had ever stamped this
        "first_press": created_work,
    }


# ------------------------------------------------------------ take it home ----


@bp.get("/export")
@require_handle
def export():
    """Everything we hold on you, in the same shape as the widget's own file."""
    rows = g.db.scalars(
        select(Rating).join(Work).where(Rating.user_id == g.user.id).order_by(Rating.rated_at)
    ).all()
    return jsonify(
        ok=True,
        handle=g.user.handle,
        exported_at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        ratings=[presenters.rating(r, viewer=g.user, include_work=True) for r in rows],
    )


@bp.delete("/account")
@require_handle
def delete_account():
    """Leave properly: every rating goes, and any song nobody else was standing
    behind goes with them."""
    if (request.get_json(silent=True) or {}).get("confirm") != g.user.handle:
        raise ApiError("type your handle to confirm", 400, "confirm_required")

    works = g.db.scalars(
        select(Work).join(Rating).where(Rating.user_id == g.user.id)
    ).unique().all()

    for rating in g.db.scalars(select(Rating).where(Rating.user_id == g.user.id)):
        rating.work.rating_count -= 1
        rating.work.rating_sum = float(rating.work.rating_sum) - float(rating.value)
        g.db.delete(rating)
    g.db.flush()

    for work in works:
        if work.rating_count <= 0:
            g.db.delete(work)

    g.db.delete(g.user)
    g.db.flush()
    from ..security import log_out

    log_out()
    return jsonify(ok=True, gone=True)


# --------------------------------------------------------------- one work ----


@bp.get("/works/<key>")
def get_one_work(key):
    """404 is the honest answer for a song nobody has ever rated.

    Not an empty object with a zero in it — there is genuinely nothing here, and
    the widget turns that into 'be the first press'.
    """
    work = get_work(g.db, key)
    if work is None:
        return jsonify(ok=False, exists=False, work_key=key), 404

    viewer = getattr(g, "user", None)
    yours = None
    if viewer is not None:
        yours = g.db.scalar(
            select(Rating).where(Rating.user_id == viewer.id, Rating.work_id == work.id)
        )
    return jsonify(
        ok=True,
        exists=True,
        work=presenters.work(work, first_presser=first_press(g.db, work), viewer_rating=yours),
    )
