"""Creating and finding the person behind a login.

The delicate part is linking: when someone signs in with Google using an address
that already has a password account here, do we hand them that account? Yes —
but *only* if the provider states the address is verified. Otherwise anyone who
can create an account at a sloppy provider claiming victim@example.com would
inherit the victim's account here. Discord and Google both report verification;
we refuse to auto-link when they don't.
"""

from sqlalchemy import select

from ..models import Identity, User, utcnow
from . import passwords, tokens


class AccountError(Exception):
    pass


def normalize_email(email):
    """Lowercase and trim. Deliberately no dot-stripping or plus-tag removal —
    those are Gmail's rules, not everyone's, and applying them globally merges
    addresses that genuinely belong to different people."""
    return (email or "").strip().casefold()


def find_by_email(session, email):
    ci = normalize_email(email)
    if not ci:
        return None
    return session.scalar(select(User).where(User.email_ci == ci, User.deleted_at.is_(None)))


# ------------------------------------------------------------------- email ----


def signup_with_email(session, email, password, display_name=None):
    """Create an unverified account. Returns (user, verification_token)."""
    ci = normalize_email(email)
    if "@" not in ci or "." not in ci.split("@")[-1]:
        raise AccountError("that doesn't look like an email address")
    if find_by_email(session, ci):
        # NB: callers must not leak this to the browser — see api/auth.py, which
        # answers identically whether or not the address was already registered
        raise AccountError("already registered")

    user = User(
        email=email.strip(),
        email_ci=ci,
        password_hash=passwords.hash_password(password),
        display_name=(display_name or "").strip()[:40] or None,
    )
    session.add(user)
    session.flush()
    return user, tokens.issue(session, user, "verify")


def login_with_email(session, email, password):
    user = find_by_email(session, email)
    if user is None or user.is_banned:
        # still burn the time a real verify would take, so the response time
        # doesn't tell an attacker which addresses exist
        passwords.verify(None, password)
        return None
    return user if passwords.verify(user, password) else None


def verify_email(session, token):
    user = tokens.redeem(session, token, "verify")
    if user is None:
        return None
    user.email_verified_at = utcnow()
    session.flush()
    return user


def reset_password(session, token, new_password):
    user = tokens.redeem(session, token, "reset")
    if user is None:
        return None
    user.password_hash = passwords.hash_password(new_password)
    # completing a reset proves control of the mailbox
    if user.email_verified_at is None:
        user.email_verified_at = utcnow()
    session.flush()
    return user


# ------------------------------------------------------------------- oauth ----


def user_for_oauth(session, provider, provider_uid, email=None, email_verified=False,
                   display_name=None):
    """Find or create the account behind a Google/Discord login.

    Returns (user, created).
    """
    provider_uid = str(provider_uid)
    identity = session.scalar(
        select(Identity).where(
            Identity.provider == provider, Identity.provider_uid == provider_uid
        )
    )
    if identity is not None:
        return session.get(User, identity.user_id), False

    user = None
    ci = normalize_email(email)
    if ci and email_verified:
        # safe to link: the provider vouches for this address
        user = find_by_email(session, ci)

    created = user is None
    if created:
        # An address we cannot prove they own is never written onto the account.
        # Claiming it would both squat the real owner's address and collide with
        # them if they already have an account — so it stays on the identity row
        # only, and they can add and verify an email later if they want one.
        claimable = bool(ci) and email_verified and find_by_email(session, ci) is None
        user = User(
            email=email.strip() if claimable else None,
            email_ci=ci if claimable else None,
            # a provider that verified the address counts as verification here
            email_verified_at=utcnow() if claimable else None,
            display_name=(display_name or "").strip()[:40] or None,
        )
        session.add(user)
        session.flush()

    session.add(
        Identity(
            user_id=user.id,
            provider=provider,
            provider_uid=provider_uid,
            email_at_provider=email,
        )
    )
    session.flush()
    return user, created
