"""Signup, login, verification, and claiming a name."""

from datetime import timedelta

from flask import current_app, g, jsonify, request

from .. import emailer as mail
from ..auth import accounts, handles, passwords, tokens
from ..security import ApiError, current_device, current_user, log_in, log_out, rate_limit, require_user
from . import bp, presenters


def body():
    return request.get_json(silent=True) or {}


def _send(user, kind):
    """Post a verification or reset mail. Never tell the caller whether the
    address existed — that's an account-enumeration oracle."""
    if user is None or not user.email:
        return
    token = tokens.issue(g.db, user, "verify" if kind == "verify" else "reset")
    base = current_app.config["BASE_URL"]
    subject, text = (
        mail.verification(base, token) if kind == "verify" else mail.password_reset(base, token)
    )
    try:
        current_app.extensions["emailer"].send(user.email, subject, text)
    except Exception:  # a dead SMTP server must not 500 a signup
        current_app.logger.exception("could not send %s mail", kind)


# ------------------------------------------------------------------ signup ----


@bp.post("/auth/signup")
def signup():
    rate_limit(g.db, "signup", limit=5, per=timedelta(hours=1))
    data = body()
    try:
        user, _token = accounts.signup_with_email(
            g.db, data.get("email"), data.get("password"), data.get("display_name")
        )
    except accounts.AccountError as exc:
        if str(exc) == "already registered":
            # answer exactly as if it had worked, and mail the real owner a
            # "someone tried to sign up as you" nudge by way of the reset flow
            _send(accounts.find_by_email(g.db, data.get("email")), "reset")
            return jsonify(ok=True, check_your_email=True)
        raise ApiError(str(exc), 400, "signup_failed")
    except passwords.WeakPassword as exc:
        raise ApiError(str(exc), 400, "weak_password")

    _send(user, "verify")
    log_in(user)
    return jsonify(ok=True, check_your_email=True, me=presenters.me(user))


@bp.post("/auth/login")
def login():
    rate_limit(g.db, "login", limit=10, per=timedelta(minutes=5))
    data = body()
    user = accounts.login_with_email(g.db, data.get("email"), data.get("password"))
    if user is None:
        raise ApiError("that email and password don't match", 401, "bad_credentials")
    log_in(user)
    return jsonify(ok=True, me=presenters.me(user))


@bp.post("/auth/logout")
def logout():
    log_out()
    return jsonify(ok=True)


@bp.post("/auth/verify")
def verify():
    rate_limit(g.db, "verify", limit=20, per=timedelta(hours=1))
    user = accounts.verify_email(g.db, body().get("token"))
    if user is None:
        raise ApiError("that link has expired or already been used", 400, "bad_token")
    log_in(user)
    return jsonify(ok=True, me=presenters.me(user))


@bp.post("/auth/resend")
@require_user
def resend_verification():
    rate_limit(g.db, "resend", limit=3, per=timedelta(hours=1), key=str(g.user.id))
    _send(g.user, "verify")
    return jsonify(ok=True)


@bp.post("/auth/forgot")
def forgot():
    rate_limit(g.db, "forgot", limit=5, per=timedelta(hours=1))
    _send(accounts.find_by_email(g.db, body().get("email")), "reset")
    return jsonify(ok=True, check_your_email=True)  # same answer either way


@bp.post("/auth/reset")
def reset():
    rate_limit(g.db, "reset", limit=10, per=timedelta(hours=1))
    data = body()
    try:
        user = accounts.reset_password(g.db, data.get("token"), data.get("password"))
    except passwords.WeakPassword as exc:
        raise ApiError(str(exc), 400, "weak_password")
    if user is None:
        raise ApiError("that link has expired or already been used", 400, "bad_token")
    log_in(user)
    return jsonify(ok=True, me=presenters.me(user))


# --------------------------------------------------------------------- me ----


@bp.get("/me")
@require_user
def get_me():
    return jsonify(ok=True, me=presenters.me(g.user, current_device(g.db)))


@bp.patch("/me")
@require_user
def patch_me():
    data = body()
    user = g.user
    if "display_name" in data:
        user.display_name = (data["display_name"] or "").strip()[:40] or None
    if "bio" in data:
        user.bio = (data["bio"] or "").strip()[:200] or None
    if "is_private" in data:
        user.is_private = bool(data["is_private"])
    if "notes_private_default" in data:
        user.notes_private_default = bool(data["notes_private_default"])
    g.db.flush()
    return jsonify(ok=True, me=presenters.me(user))


# ---------------------------------------------------------------- handles ----


@bp.get("/handle/available")
def handle_available():
    wanted = request.args.get("handle", "")
    try:
        free = handles.is_available(g.db, wanted, for_user=current_user(g.db))
    except handles.HandleError as exc:
        return jsonify(ok=True, available=False, reason=str(exc))
    return jsonify(
        ok=True,
        available=free,
        reason=None if free else "that one's taken",
        suggestion=None if free else handles.suggest(g.db, wanted),
    )


@bp.post("/handle/claim")
@require_user
def claim_handle():
    rate_limit(g.db, "handle", limit=10, per=timedelta(hours=1), key=str(g.user.id))
    try:
        handles.claim(g.db, g.user, body().get("handle"))
    except handles.HandleError as exc:
        raise ApiError(str(exc), 400, "handle_rejected")
    return jsonify(ok=True, me=presenters.me(g.user))
