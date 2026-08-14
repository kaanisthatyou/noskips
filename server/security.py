"""Who is asking, and how often.

Two kinds of caller reach the API and they authenticate differently:

  * a **browser**, carrying a signed session cookie set at login;
  * a **paired widget**, carrying an opaque device token in the Authorization
    header — no cookie, no CSRF surface, no OAuth secret on the client.

``current_user`` resolves either. Handlers that must know which one they got
(rating provenance, for instance) can ask for ``current_device``.
"""

import functools
import uuid
from datetime import timedelta

from flask import current_app, g, jsonify, request, session as flask_session
from sqlalchemy import select

from .auth import pairing
from .models import RateLimit, User, utcnow

SESSION_KEY = "uid"


def as_uuid(value):
    """UUIDs arrive as strings from cookies and URLs; the columns want objects.

    A malformed one is 'no such thing', never a 500 — these values come
    straight from the outside world.
    """
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, AttributeError, TypeError):
        return None


class ApiError(Exception):
    """An error with a status code, rendered as JSON by the blueprint."""

    def __init__(self, message, status=400, code=None):
        super().__init__(message)
        self.message = message
        self.status = status
        self.code = code or "error"


# ------------------------------------------------------------------- login ----


def log_in(user):
    flask_session[SESSION_KEY] = str(user.id)
    flask_session.permanent = True


def log_out():
    flask_session.pop(SESSION_KEY, None)


def current_device(db):
    """The widget behind this request, if it's a widget."""
    if "device" in g:
        return g.device
    header = request.headers.get("Authorization", "")
    token = header[7:].strip() if header.lower().startswith("bearer ") else None
    g.device = pairing.authenticate(db, token) if token else None
    return g.device


def current_user(db):
    """The person behind this request, browser or widget, or None."""
    if "user" in g:
        return g.user
    g.user = None

    device = current_device(db)
    if device is not None:
        g.user = db.get(User, device.user_id)
    else:
        uid = as_uuid(flask_session.get(SESSION_KEY))
        if uid:
            g.user = db.scalar(select(User).where(User.id == uid, User.deleted_at.is_(None)))

    if g.user is not None and (g.user.is_banned or g.user.deleted_at is not None):
        g.user = None
    return g.user


def require_user(fn):
    """Handlers that need somebody signed in."""

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user(g.db)
        if user is None:
            raise ApiError("sign in first", 401, "unauthenticated")
        return fn(*args, **kwargs)

    return wrapper


def require_handle(fn):
    """Handlers that need somebody who has actually claimed a name.

    Rating, following and cosigning are all public acts, so they wait until
    there's a name attached to them.
    """

    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        user = current_user(g.db)
        if user is None:
            raise ApiError("sign in first", 401, "unauthenticated")
        if not user.handle_ci:
            raise ApiError("claim a handle first", 403, "no_handle")
        return fn(*args, **kwargs)

    return wrapper


# -------------------------------------------------------------- rate limits ----


def client_ip():
    # Vercel and Cloudflare both put the real client first in this header
    forwarded = request.headers.get("X-Forwarded-For", "")
    return forwarded.split(",")[0].strip() or request.remote_addr or "unknown"


def rate_limit(db, name, limit, per=timedelta(minutes=1), key=None):
    """Fixed-window limiter. Raises ApiError(429) when the bucket is spent.

    Fixed windows let through up to 2x the limit across a boundary, which is
    fine here: this exists to stop scripted abuse, not to meter a paid API.
    """
    if current_app.config.get("RATE_LIMITS_DISABLED"):
        return
    seconds = int(per.total_seconds())
    now = utcnow()
    window_start = now.replace(microsecond=0) - timedelta(
        seconds=(int(now.timestamp()) % seconds)
    )
    bucket = f"{name}:{key or client_ip()}"

    row = db.scalar(
        select(RateLimit).where(
            RateLimit.bucket == bucket, RateLimit.window_start == window_start
        )
    )
    if row is None:
        row = RateLimit(bucket=bucket, window_start=window_start, count=0)
        db.add(row)
    row.count += 1
    db.flush()

    if row.count > limit:
        raise ApiError("slow down a moment", 429, "rate_limited")


def json_error(err):
    payload = {"ok": False, "error": err.message, "code": err.code}
    return jsonify(payload), err.status
