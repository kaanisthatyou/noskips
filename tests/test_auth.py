"""Auth tests. Deliberately no network and no provider credentials — the parts
that can actually be got wrong (linking, expiry, single use, rename limits,
who can collect a device token) are all local logic.
"""

from datetime import timedelta

import pytest
from sqlalchemy import select

from server.auth import accounts, handles, pairing, passwords, tokens
from server.models import Device, EmailToken, Identity, Pairing, User, utcnow

# ------------------------------------------------------------------ passwords ----


def test_password_round_trip(session):
    u = User(password_hash=passwords.hash_password("correct horse battery"))
    assert passwords.verify(u, "correct horse battery") is True
    assert passwords.verify(u, "wrong horse battery") is False


def test_short_passwords_rejected():
    with pytest.raises(passwords.WeakPassword):
        passwords.hash_password("short")


def test_verify_against_an_oauth_only_account_is_false():
    """No password set must never mean 'any password works'."""
    assert passwords.verify(User(password_hash=None), "anything") is False


# --------------------------------------------------------------------- tokens ----


def test_token_is_single_use(session, users):
    tok = tokens.issue(session, users[0], "verify")
    assert tokens.redeem(session, tok, "verify").id == users[0].id
    assert tokens.redeem(session, tok, "verify") is None


def test_token_expires(session, users):
    tok = tokens.issue(session, users[0], "verify")
    row = session.scalar(select(EmailToken).where(EmailToken.used_at.is_(None)))
    row.expires_at = utcnow() - timedelta(minutes=1)
    session.flush()
    assert tokens.redeem(session, tok, "verify") is None


def test_issuing_a_new_token_kills_the_old_one(session, users):
    """An old 'reset your password' email must stop being a live key."""
    first = tokens.issue(session, users[0], "reset")
    second = tokens.issue(session, users[0], "reset")
    assert tokens.redeem(session, first, "reset") is None
    assert tokens.redeem(session, second, "reset").id == users[0].id


def test_a_verify_token_cannot_be_spent_as_a_reset(session, users):
    tok = tokens.issue(session, users[0], "verify")
    assert tokens.redeem(session, tok, "reset") is None


def test_only_the_hash_is_stored(session, users):
    tok = tokens.issue(session, users[0], "verify")
    row = session.scalar(select(EmailToken))
    assert tok not in row.token_hash
    assert len(row.token_hash) == 64


# -------------------------------------------------------------------- signup ----


def test_signup_then_verify(session):
    user, tok = accounts.signup_with_email(session, "Kaan@Example.COM ", "a good long one")
    assert user.email_ci == "kaan@example.com"
    assert user.email_verified_at is None

    assert accounts.verify_email(session, tok).id == user.id
    assert user.email_verified_at is not None


def test_signup_is_case_insensitive_about_duplicates(session):
    accounts.signup_with_email(session, "kaan@example.com", "a good long one")
    with pytest.raises(accounts.AccountError):
        accounts.signup_with_email(session, "KAAN@EXAMPLE.COM", "another long one")


def test_login_requires_the_right_password(session):
    accounts.signup_with_email(session, "kaan@example.com", "a good long one")
    assert accounts.login_with_email(session, "kaan@example.com", "nope") is None
    assert accounts.login_with_email(session, "kaan@example.com", "a good long one")


def test_banned_users_cannot_log_in(session):
    user, _ = accounts.signup_with_email(session, "kaan@example.com", "a good long one")
    user.is_banned = True
    session.flush()
    assert accounts.login_with_email(session, "kaan@example.com", "a good long one") is None


def test_completing_a_reset_verifies_the_address(session):
    user, _ = accounts.signup_with_email(session, "kaan@example.com", "a good long one")
    tok = tokens.issue(session, user, "reset")

    accounts.reset_password(session, tok, "a different long one")

    assert user.email_verified_at is not None
    assert accounts.login_with_email(session, "kaan@example.com", "a different long one")


# --------------------------------------------------------------------- oauth ----


def test_oauth_creates_an_account_then_reuses_it(session):
    first, created = accounts.user_for_oauth(
        session, "google", "123", "kaan@example.com", email_verified=True
    )
    assert created is True

    again, created = accounts.user_for_oauth(
        session, "google", "123", "kaan@example.com", email_verified=True
    )
    assert created is False and again.id == first.id


def test_verified_oauth_links_to_an_existing_password_account(session):
    user, _ = accounts.signup_with_email(session, "kaan@example.com", "a good long one")

    linked, created = accounts.user_for_oauth(
        session, "google", "123", "kaan@example.com", email_verified=True
    )

    assert created is False and linked.id == user.id


def test_unverified_oauth_email_does_NOT_link(session):
    """The account-takeover case: a provider that won't vouch for the address
    must not hand over someone else's account."""
    user, _ = accounts.signup_with_email(session, "kaan@example.com", "a good long one")

    other, created = accounts.user_for_oauth(
        session, "discord", "999", "kaan@example.com", email_verified=False
    )

    assert created is True
    assert other.id != user.id
    # and it must not squat the address on the way past
    assert other.email_ci is None
    assert user.email_ci == "kaan@example.com"


def test_an_unverified_oauth_address_is_never_claimed(session):
    """Even when nobody owns it yet: claiming an address we can't prove they
    control would lock out whoever actually does."""
    user, _ = accounts.user_for_oauth(
        session, "discord", "999", "nobody@example.com", email_verified=False
    )

    assert user.email_ci is None
    assert user.email_verified_at is None
    # the address is still recorded against the identity, just not trusted
    assert session.scalar(select(Identity)).email_at_provider == "nobody@example.com"


def test_two_providers_same_person(session):
    google, _ = accounts.user_for_oauth(
        session, "google", "123", "kaan@example.com", email_verified=True
    )
    discord, created = accounts.user_for_oauth(
        session, "discord", "999", "kaan@example.com", email_verified=True
    )
    assert created is False and discord.id == google.id


# ------------------------------------------------------------------- handles ----


@pytest.mark.parametrize("bad", ["ab", "a" * 21, "has space", "Ünïcode", "dash-es", ""])
def test_bad_handles_rejected(bad):
    with pytest.raises(handles.HandleError):
        handles.validate(bad)


@pytest.mark.parametrize("reserved", ["api", "settings", "admin", "album", "me"])
def test_reserved_handles_rejected(reserved):
    with pytest.raises(handles.HandleError):
        handles.validate(reserved)


def test_handle_uniqueness_is_case_insensitive(session, users):
    fresh = User()
    session.add(fresh)
    session.flush()
    with pytest.raises(handles.HandleError):
        handles.claim(session, fresh, "KAAN")


def test_claiming_sets_both_forms(session):
    u = User()
    session.add(u)
    session.flush()
    handles.claim(session, u, "@Kaan_99")
    assert (u.handle, u.handle_ci) == ("Kaan_99", "kaan_99")


def test_renaming_is_rate_limited(session):
    u = User()
    session.add(u)
    session.flush()
    handles.claim(session, u, "first_one")

    with pytest.raises(handles.HandleError):
        handles.claim(session, u, "second_one")


def test_rename_allowed_after_the_cooldown(session):
    u = User()
    session.add(u)
    session.flush()
    handles.claim(session, u, "first_one")
    u.handle_changed_at = utcnow() - handles.RENAME_EVERY - timedelta(days=1)
    session.flush()

    handles.claim(session, u, "second_one")
    assert u.handle_ci == "second_one"


def test_fixing_your_own_capitalisation_is_free(session):
    u = User()
    session.add(u)
    session.flush()
    handles.claim(session, u, "kaan_99")
    handles.claim(session, u, "Kaan_99")  # no cooldown error
    assert u.handle == "Kaan_99"


def test_suggest_avoids_taken_handles(session, users):
    assert handles.suggest(session, "kaan") == "kaan2"
    assert handles.suggest(session, "brand new") == "brandnew"


# ------------------------------------------------------------------- pairing ----

NONCE = "a" * 32


def test_pairing_happy_path(session, users):
    code = pairing.start(session, NONCE, device_name="kaan's pc", app_version="2.0.0")

    assert pairing.poll(session, NONCE) is None  # nobody has approved it yet

    device = pairing.approve(session, code, users[0])
    token = pairing.poll(session, NONCE)

    assert token
    assert pairing.authenticate(session, token).id == device.id


def test_the_token_is_handed_over_exactly_once(session, users):
    code = pairing.start(session, NONCE)
    pairing.approve(session, code, users[0])

    assert pairing.poll(session, NONCE)
    assert pairing.poll(session, NONCE) is None


def test_a_different_device_cannot_collect_the_token(session, users):
    """The code alone is not enough — this is what stops a guessed or phished
    code from handing someone else's account to the attacker's widget."""
    code = pairing.start(session, NONCE)
    pairing.approve(session, code, users[0])

    assert pairing.poll(session, "b" * 32) is None
    assert pairing.poll(session, NONCE)  # the real device still can


def test_expired_codes_are_refused(session, users):
    code = pairing.start(session, NONCE)
    row = session.scalar(select(Pairing).where(Pairing.code == code))
    row.expires_at = utcnow() - timedelta(seconds=1)
    session.flush()

    with pytest.raises(pairing.PairingError):
        pairing.approve(session, code, users[0])


def test_a_code_cannot_be_approved_twice(session, users):
    code = pairing.start(session, NONCE)
    pairing.approve(session, code, users[0])

    with pytest.raises(pairing.PairingError):
        pairing.approve(session, code, users[1])


def test_unknown_codes_are_refused(session):
    with pytest.raises(pairing.PairingError):
        pairing.lookup(session, "ZZZZZZ")


def test_revoked_devices_stop_authenticating(session, users):
    code = pairing.start(session, NONCE)
    pairing.approve(session, code, users[0])
    token = pairing.poll(session, NONCE)

    pairing.revoke(session, session.scalar(select(Device)))

    assert pairing.authenticate(session, token) is None


def test_only_the_token_hash_is_stored(session, users):
    code = pairing.start(session, NONCE)
    pairing.approve(session, code, users[0])
    token = pairing.poll(session, NONCE)

    device = session.scalar(select(Device))
    assert token not in device.token_hash
    # and the plaintext is not left lying in the pairing row afterwards
    assert session.scalar(select(Pairing)).device_token is None


def test_codes_avoid_easily_confused_characters(session):
    code = pairing.start(session, NONCE)
    assert not (set(code) & set("ILOU"))
    assert pairing.format_code("K74QXB") == "K74-QXB"
    assert pairing.parse_code(" k74-qxb ") == "K74QXB"
