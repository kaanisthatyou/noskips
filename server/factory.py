"""The Flask application.

One app serves the API, the web pages and (eventually) the marketing site, so
there is one deploy, one stylesheet and one place session cookies come from.

Configuration is entirely environment variables — nothing secret is ever
committed, and the same image runs locally on SQLite and on Neon in production:

    SECRET_KEY          signs session cookies (required in production)
    DATABASE_URL        Neon's *pooled* connection string in production
    BASE_URL            public origin, used in emails and pairing links
    GOOGLE_CLIENT_ID / _SECRET, DISCORD_CLIENT_ID / _SECRET   optional
    EMAIL_BACKEND=smtp plus SMTP_*                            optional
"""

import os
from datetime import timedelta
from pathlib import Path

from flask import Flask, g, jsonify, request

from . import db as database
from . import emailer
from .auth import oauth
from .security import ApiError, json_error


REPO_ROOT = Path(__file__).resolve().parent.parent


def create_app(config=None):
    # serve the widget's own static folder, so the web page uses the same
    # Special Elite and Caveat files the widget does rather than a lookalike
    app = Flask(
        __name__,
        static_folder=str(REPO_ROOT / "static"),
        static_url_path="/static",
    )
    # `or` rather than a get default throughout: .env.example ships every key
    # present and empty, so a copied .env sets them to "" and a two-argument
    # get would hand an empty SECRET_KEY to the cookie signer. See server/db.py.
    base_url = os.environ.get("BASE_URL") or "http://127.0.0.1:5000"
    app.config.update(
        SECRET_KEY=os.environ.get("SECRET_KEY") or "dev-only-not-a-secret",
        BASE_URL=base_url,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=base_url.startswith("https"),
        PERMANENT_SESSION_LIFETIME=timedelta(days=90),
        JSON_SORT_KEYS=False,
        MAX_CONTENT_LENGTH=1024 * 1024,  # a sync batch has no business being bigger
    )
    if config:
        app.config.update(config)

    if app.config["SECRET_KEY"] == "dev-only-not-a-secret" and not app.debug:
        # loud, but not fatal: a misconfigured deploy should be obvious in logs
        # rather than silently signing everyone's cookies with a known key
        app.logger.warning("SECRET_KEY is unset — sessions are NOT secure")

    app.extensions["emailer"] = app.config.get("EMAILER") or emailer.from_env()
    oauth.init_app(app)

    # ------------------------------------------------------- request scope ----

    @app.before_request
    def open_session():
        database.engine()
        g.db = database._Session()

    @app.before_request
    def honour_the_kill_switch():
        """RATEIFY_READ_ONLY=1 stops every write while leaving the site fully
        readable — the thing you want at 2am when something is going wrong and
        you'd rather freeze it than take it down."""
        from .web.admin import read_only

        if request.method in ("GET", "HEAD", "OPTIONS") or not read_only():
            return None
        raise ApiError("rateify is read-only for a moment — nothing was lost", 503, "read_only")

    @app.teardown_request
    def close_session(exc):
        s = g.pop("db", None)
        if s is None:
            return
        try:
            if exc is None:
                s.commit()
            else:
                s.rollback()
        finally:
            s.close()

    @app.errorhandler(ApiError)
    def handle_api_error(err):
        # a failed request must not half-commit; roll back before responding
        if "db" in g:
            g.db.rollback()
        return json_error(err)

    @app.get("/healthz")
    def healthz():
        return jsonify(ok=True, service="rateify")

    # ------------------------------------------------------------ routing ----

    from .api import bp as api_bp
    from .web import bp as web_bp
    from .web.oauth_routes import bp as oauth_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(oauth_bp)
    app.register_blueprint(web_bp)

    return app
