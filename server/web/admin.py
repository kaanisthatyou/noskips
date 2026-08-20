"""The moderation queue and the kill switch.

Small on purpose. A one-person project doesn't need a moderation console, it
needs to be able to answer a bad week at 2am from a phone: see what was
reported, hide it, ban whoever posted it, and — if something is really wrong —
stop the world from writing while you think.

Access is by handle from the ADMIN_HANDLES environment variable rather than a
role column, so there's no "make me an admin" code path to find a bug in.
"""

import os

from flask import abort, current_app, g, jsonify, redirect, render_template, request
from sqlalchemy import select

from ..envcompat import env
from ..models import Rating, Report, User, utcnow
from ..security import ApiError, as_uuid, current_user
from . import bp


def admins():
    return {h.strip().casefold() for h in os.environ.get("ADMIN_HANDLES", "").split(",") if h.strip()}


def require_admin():
    me = current_user(g.db)
    if me is None or not me.handle_ci or me.handle_ci not in admins():
        abort(404)  # not 403: an admin page nobody can see shouldn't announce itself
    return me


def read_only():
    """The kill switch. Set RATEIFY_READ_ONLY=1 and every write stops while
    everything stays readable. The old NOSKIPS_READ_ONLY still works, so a
    deployment that was frozen before the rename stays frozen after it."""
    return (env("READ_ONLY") or "") not in ("", "0", "false")


@bp.get("/admin")
def queue():
    require_admin()
    reports = g.db.scalars(
        select(Report).where(Report.resolved_at.is_(None)).order_by(Report.created_at.desc()).limit(100)
    ).all()

    rows = []
    for report in reports:
        rating = g.db.get(Rating, report.target_rating_id) if report.target_rating_id else None
        subject = rating.user if rating else (
            g.db.get(User, report.target_user_id) if report.target_user_id else None
        )
        rows.append({"report": report, "rating": rating, "subject": subject})

    return render_template("admin.html", rows=rows, read_only=read_only())


@bp.post("/admin/act")
def act():
    me = require_admin()
    action = request.form.get("action")
    report = g.db.get(Report, as_uuid(request.form.get("report_id")))
    if report is None:
        abort(404)

    if action == "hide" and report.target_rating_id:
        rating = g.db.get(Rating, report.target_rating_id)
        if rating:
            # hidden, not deleted: their own copy stays theirs, it just leaves
            # every public surface
            rating.is_public = False
            rating.note_public = False
    elif action == "ban":
        rating = g.db.get(Rating, report.target_rating_id) if report.target_rating_id else None
        target = rating.user if rating else g.db.get(User, report.target_user_id)
        if target and target.handle_ci not in admins():
            target.is_banned = True

    report.resolved_at = utcnow()
    current_app.logger.warning("moderation: %s by @%s on report %s", action, me.handle, report.id)
    g.db.flush()
    return redirect("/admin")
