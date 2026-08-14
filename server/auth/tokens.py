"""Email verification and password-reset tokens.

Two properties matter and both are easy to get wrong:

1. **Only the hash is stored.** A database leak must not hand out account
   takeovers, so the plaintext token exists exactly once, in the email we send.
2. **Single use, and expiring.** Used and expired tokens are both dead, and
   issuing a new one of the same purpose kills the outstanding ones — otherwise
   an old "reset your password" email stays a live key forever.
"""

import hashlib
import secrets
from datetime import timedelta

from sqlalchemy import select

from ..models import EmailToken, utcnow

VERIFY_TTL = timedelta(hours=24)
RESET_TTL = timedelta(hours=1)  # shorter: a reset link is a bearer credential


def _hash(token):
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def issue(session, user, purpose="verify"):
    """Mint a token, storing only its hash. Returns the plaintext — the single
    copy that ever exists — for the caller to put in an email."""
    # any outstanding token of this purpose stops working now
    for old in session.scalars(
        select(EmailToken).where(
            EmailToken.user_id == user.id,
            EmailToken.purpose == purpose,
            EmailToken.used_at.is_(None),
        )
    ):
        old.used_at = utcnow()

    token = secrets.token_urlsafe(32)
    ttl = VERIFY_TTL if purpose == "verify" else RESET_TTL
    session.add(
        EmailToken(
            user_id=user.id,
            token_hash=_hash(token),
            purpose=purpose,
            expires_at=utcnow() + ttl,
        )
    )
    session.flush()
    return token


def redeem(session, token, purpose="verify"):
    """Spend a token, returning its user — or None if it's wrong, already used,
    or expired. Callers must not distinguish between those cases out loud."""
    if not token:
        return None
    row = session.scalar(
        select(EmailToken).where(
            EmailToken.token_hash == _hash(token), EmailToken.purpose == purpose
        )
    )
    if row is None or row.used_at is not None:
        return None

    expires = row.expires_at
    if expires.tzinfo is None:  # SQLite hands back naive datetimes
        from datetime import timezone

        expires = expires.replace(tzinfo=timezone.utc)
    if expires < utcnow():
        return None

    row.used_at = utcnow()
    session.flush()
    from ..models import User

    return session.get(User, row.user_id)
