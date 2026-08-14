"""Signing a desktop widget in without giving it any secrets.

The widget is an exe on a stranger's machine. Anything shipped inside it — an
OAuth client secret, an API key — is public the moment it ships, and asking it
to collect a password would make every future phishing clone credible. So it
never gets credentials at all:

    widget   POST /v1/pair/start  {nonce}   -> a short code + a URL
    widget   opens that URL in the real browser
    person   logs in normally there, sees the device, approves it
    widget   POST /v1/pair/poll   {nonce}   -> its own long-lived device token

The login happens in a real browser, where OAuth redirects work properly and
the person can see the address bar. The widget only ever learns the resulting
token, which is scoped to one device and revocable from the web.

**The known weakness**, spelled out because it's the whole risk surface: an
attacker can start a pairing and try to talk a victim into approving *their*
code ("paste this to fix your sync"). The code is useless without the nonce, so
the attacker cannot collect the token — but the victim could still approve a
device that isn't theirs. Defences: a ten-minute TTL, rate limiting on claim,
and a confirmation page that names the device and says plainly to continue only
if they *just* opened noskips themselves.
"""

import hashlib
import secrets
from datetime import timedelta, timezone

from sqlalchemy import select

from ..models import Device, Pairing, utcnow

# Crockford base32: no I, L, O or U, so nothing is misread aloud or mistyped
CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
CODE_LEN = 6
PAIRING_TTL = timedelta(minutes=10)
MAX_CODE_ATTEMPTS = 8


class PairingError(Exception):
    pass


def _hash(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _aware(dt):
    return dt.replace(tzinfo=timezone.utc) if dt is not None and dt.tzinfo is None else dt


def format_code(code):
    """K74QXB -> K74-QXB, which is what people actually manage to read out."""
    half = len(code) // 2
    return f"{code[:half]}-{code[half:]}"


def parse_code(code):
    return "".join(c for c in (code or "").upper() if c in CODE_ALPHABET)


def _fresh_code(session):
    for _ in range(20):
        code = "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LEN))
        if not session.scalar(select(Pairing).where(Pairing.code == code)):
            return code
    raise PairingError("could not allocate a pairing code")  # pragma: no cover


# ------------------------------------------------------------------ widget ----


def start(session, device_nonce, device_name=None, app_version=None):
    """Called by the widget. Returns the code to show the user."""
    if not device_nonce or len(device_nonce) < 16:
        raise PairingError("device_nonce must be at least 16 characters")

    code = _fresh_code(session)
    session.add(
        Pairing(
            code=code,
            device_nonce_hash=_hash(device_nonce),
            device_name=(device_name or "")[:60] or None,
            app_version=(app_version or "")[:20] or None,
            expires_at=utcnow() + PAIRING_TTL,
        )
    )
    session.flush()
    return code


def poll(session, device_nonce):
    """Called by the widget every couple of seconds.

    Returns the device token exactly once, then forgets it. Returns None while
    the person hasn't approved it yet — which is the normal case, not an error.
    """
    if not device_nonce:
        return None
    pairing = session.scalar(
        select(Pairing)
        .where(
            Pairing.device_nonce_hash == _hash(device_nonce),
            Pairing.collected_at.is_(None),
        )
        .order_by(Pairing.created_at.desc())
    )
    if pairing is None or pairing.device_token is None:
        return None
    if _aware(pairing.expires_at) < utcnow():
        return None

    token = pairing.device_token
    pairing.device_token = None  # held for exactly one collection
    pairing.collected_at = utcnow()
    session.flush()
    return token


# ----------------------------------------------------------------- browser ----


def lookup(session, code):
    """Find a pending pairing so the confirmation page can describe it."""
    pairing = session.scalar(select(Pairing).where(Pairing.code == parse_code(code)))
    if pairing is None:
        raise PairingError("that code isn't valid — check the widget again")
    if pairing.claimed_at is not None:
        raise PairingError("that code has already been used")
    if _aware(pairing.expires_at) < utcnow():
        raise PairingError("that code expired — open the widget for a fresh one")
    return pairing


def approve(session, code, user, device_name=None):
    """Called from the browser once the person has logged in and confirmed.

    Creates the device and stashes its token for the widget's next poll.
    """
    pairing = lookup(session, code)

    token = secrets.token_urlsafe(32)
    device = Device(
        user_id=user.id,
        token_hash=_hash(token),
        name=device_name or pairing.device_name or "a windows pc",
        app_version=pairing.app_version,
    )
    session.add(device)

    pairing.user_id = user.id
    pairing.claimed_at = utcnow()
    pairing.device_token = token
    session.flush()
    return device


# -------------------------------------------------------------------- auth ----


def authenticate(session, token):
    """Resolve a device token to its device, or None. Bumps last_seen_at so the
    web settings page can show 'last synced 3 minutes ago' per device."""
    if not token:
        return None
    device = session.scalar(
        select(Device).where(Device.token_hash == _hash(token), Device.revoked_at.is_(None))
    )
    if device is None:
        return None
    device.last_seen_at = utcnow()
    return device


def revoke(session, device):
    device.revoked_at = utcnow()
    session.flush()
