"""Google and Discord sign-in.

Both providers are optional at runtime: if the environment doesn't carry
credentials for one, its buttons simply don't appear. That keeps a local
checkout runnable with no third-party setup at all — you can develop the entire
app against email signup and the console mailer.

Setup, when you do want them (both free):
  * Google — console.cloud.google.com -> APIs & Services -> Credentials ->
    OAuth client ID (Web application). Redirect URI:
    https://<host>/auth/google/callback
  * Discord — discord.com/developers -> New Application -> OAuth2. Redirect URI:
    https://<host>/auth/discord/callback
"""

import os

from authlib.integrations.flask_client import OAuth

oauth = OAuth()

GOOGLE_METADATA = "https://accounts.google.com/.well-known/openid-configuration"

_enabled = set()


def init_app(app):
    oauth.init_app(app)

    if os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"):
        oauth.register(
            name="google",
            client_id=os.environ["GOOGLE_CLIENT_ID"],
            client_secret=os.environ["GOOGLE_CLIENT_SECRET"],
            server_metadata_url=GOOGLE_METADATA,
            client_kwargs={"scope": "openid email profile"},
        )
        _enabled.add("google")

    if os.environ.get("DISCORD_CLIENT_ID") and os.environ.get("DISCORD_CLIENT_SECRET"):
        oauth.register(
            name="discord",
            client_id=os.environ["DISCORD_CLIENT_ID"],
            client_secret=os.environ["DISCORD_CLIENT_SECRET"],
            api_base_url="https://discord.com/api/",
            access_token_url="https://discord.com/api/oauth2/token",
            authorize_url="https://discord.com/api/oauth2/authorize",
            client_kwargs={"scope": "identify email"},
        )
        _enabled.add("discord")

    app.config["OAUTH_PROVIDERS"] = sorted(_enabled)
    return sorted(_enabled)


def enabled(provider):
    return provider in _enabled


def profile(provider, token):
    """Normalize a provider's user info into the shape accounts.py wants.

    ``email_verified`` is load-bearing: accounts.user_for_oauth will only link
    an OAuth login to an existing password account when the provider vouches
    for the address, so getting this flag wrong is an account-takeover bug.
    """
    if provider == "google":
        info = token.get("userinfo") or oauth.google.userinfo(token=token)
        return {
            "provider_uid": info["sub"],
            "email": info.get("email"),
            "email_verified": bool(info.get("email_verified")),
            "display_name": info.get("name") or info.get("given_name"),
        }

    if provider == "discord":
        info = oauth.discord.get("users/@me", token=token).json()
        return {
            "provider_uid": info["id"],
            "email": info.get("email"),
            "email_verified": bool(info.get("verified")),
            "display_name": info.get("global_name") or info.get("username"),
        }

    raise ValueError(f"unknown provider {provider!r}")
