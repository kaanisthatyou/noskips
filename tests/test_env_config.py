"""A blank environment variable means unset, not empty string.

.env.example ships every key present with an empty value, and docs/SERVER.md
tells you to copy it verbatim before doing anything else. That puts
``DATABASE_URL=""`` — and a dozen others — into the environment.

``os.environ.get(key, default)`` only falls back when the key is *absent*, so
the documented first-run path used to hand SQLAlchemy an empty connection
string and 500 every request on a fresh checkout. Each case below is a thing
that was actually broken by a copied .env, so a future `get(key, default)`
creeping back in fails here rather than on somebody's first afternoon.
"""

import importlib

import pytest

from server import db as database
from server import emailer, musicbrainz
from server.factory import create_app
from server.web import pages, releases


def test_blank_database_url_falls_back_to_sqlite(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "")
    assert database.database_url() == database.DEFAULT_DATABASE_URL


def test_absent_database_url_falls_back_to_sqlite(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    assert database.database_url() == database.DEFAULT_DATABASE_URL


def test_real_database_url_still_wins_and_is_normalized(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@host/db")
    assert database.database_url() == "postgresql+psycopg://u:p@host/db"


def test_blank_secret_key_does_not_sign_cookies_with_nothing(monkeypatch):
    """An empty signing key is worse than the dev placeholder, not equivalent."""
    monkeypatch.setenv("SECRET_KEY", "")
    assert create_app().config["SECRET_KEY"] == "dev-only-not-a-secret"


def test_blank_base_url_keeps_a_usable_origin(monkeypatch):
    monkeypatch.setenv("BASE_URL", "")
    app = create_app()
    assert app.config["BASE_URL"] == "http://127.0.0.1:5000"
    # and http must not be mistaken for https, or the cookie goes nowhere
    assert app.config["SESSION_COOKIE_SECURE"] is False


def test_https_base_url_still_marks_the_cookie_secure(monkeypatch):
    monkeypatch.setenv("BASE_URL", "https://noskips.example")
    assert create_app().config["SESSION_COOKIE_SECURE"] is True


def test_blank_github_repo_does_not_produce_a_double_slash(monkeypatch):
    """Every download button and the footer link read this."""
    monkeypatch.setenv("GITHUB_REPO", "")
    reloaded = importlib.reload(releases)
    try:
        assert reloaded.REPO == "kaanisthatyou/noskips"
        assert "//releases" not in reloaded.latest()["artifacts"][0]["url"]
    finally:
        monkeypatch.delenv("GITHUB_REPO", raising=False)
        importlib.reload(releases)


def test_blank_discord_invite_does_not_redirect_to_itself(monkeypatch):
    """redirect("") is a redirect to the current page — an invite that loops."""
    monkeypatch.setenv("DISCORD_INVITE", "")
    app = create_app()
    with app.test_request_context():
        response = pages.discord()
    assert response.headers["Location"] == "https://discord.gg/"


def test_blank_musicbrainz_contact_never_becomes_a_rude_user_agent(monkeypatch):
    monkeypatch.setenv("MUSICBRAINZ_CONTACT", "")
    reloaded = importlib.reload(musicbrainz)
    try:
        assert reloaded.CONTACT
    finally:
        monkeypatch.delenv("MUSICBRAINZ_CONTACT", raising=False)
        importlib.reload(musicbrainz)


def test_blank_email_backend_is_the_console_sender(monkeypatch):
    monkeypatch.setenv("EMAIL_BACKEND", "")
    assert isinstance(emailer.from_env(), emailer.ConsoleSender)


@pytest.mark.parametrize("blank", ["SMTP_HOST", "SMTP_PORT"])
def test_blank_smtp_settings_keep_their_defaults(monkeypatch, blank):
    monkeypatch.setenv("EMAIL_BACKEND", "smtp")
    monkeypatch.setenv("SMTP_USER", "someone@example.com")
    monkeypatch.setenv("SMTP_PASSWORD", "app-password")
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("SMTP_PORT", "")
    sender = emailer.from_env()
    assert sender.host == "smtp.gmail.com"
    assert sender.port == 587
    # EMAIL_FROM unset falls through to the account actually sending the mail
    assert sender.sender == "someone@example.com"
