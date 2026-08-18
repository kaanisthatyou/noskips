"""Google and Discord redirects.

These live outside /v1 because they're browser navigation, not API calls — the
widget never touches them. It sends the person here through their real browser
and waits for a token instead, which is the whole point of the pairing flow.
"""

from flask import Blueprint, current_app, g, redirect, request, session, url_for

from ..auth import accounts, oauth
from ..security import ApiError, log_in

bp = Blueprint("oauth", __name__, url_prefix="/auth")

# only ever redirect somewhere on our own site after login
SAFE_NEXT_PREFIXES = ("/", "/link", "/welcome", "/settings")


def _safe_next(value):
    if not value or not value.startswith("/") or value.startswith("//"):
        return "/"
    return value


@bp.get("/<provider>")
def start(provider):
    if not oauth.enabled(provider):
        raise ApiError(f"{provider} sign-in isn't configured", 404, "provider_off")
    session["oauth_next"] = _safe_next(request.args.get("next"))
    client = getattr(oauth.oauth, provider)
    return client.authorize_redirect(
        url_for("oauth.callback", provider=provider, _external=True)
    )


@bp.get("/<provider>/callback")
def callback(provider):
    if not oauth.enabled(provider):
        raise ApiError(f"{provider} sign-in isn't configured", 404, "provider_off")

    client = getattr(oauth.oauth, provider)
    try:
        token = client.authorize_access_token()
        info = oauth.profile(provider, token)
    except Exception:
        current_app.logger.exception("%s sign-in failed", provider)
        raise ApiError("that sign-in didn't complete — try again", 400, "oauth_failed")

    user, _created = accounts.user_for_oauth(
        g.db,
        provider,
        info["provider_uid"],
        email=info.get("email"),
        email_verified=info.get("email_verified", False),
        display_name=info.get("display_name"),
        username=info.get("username"),
    )
    if user.is_banned:
        raise ApiError("this account is suspended", 403, "banned")

    log_in(user)
    destination = session.pop("oauth_next", "/")
    # a brand new account has no name yet, and everything social needs one
    if not user.handle_ci:
        return redirect(f"/welcome?next={destination}")
    return redirect(destination)
