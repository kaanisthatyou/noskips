"""Claiming a name.

A handle is the one piece of identity everyone sees, so the rules here are
about impersonation more than about tidiness:

* uniqueness is decided on the casefolded form, so ``@kaan`` and ``@KAAN``
  cannot both exist and be mistaken for each other;
* renaming is rate-limited to once a month, and the old handle is held for a
  further 90 days, so nobody can rename and let someone else immediately pick up
  their identity along with their reputation;
* route names are reserved, because ``/settings`` must never be a person.
"""

import re
from datetime import timedelta

from sqlalchemy import select

from ..models import User, utcnow

HANDLE_RE = re.compile(r"^[a-z0-9_]{3,20}$")
RENAME_EVERY = timedelta(days=30)
OLD_HANDLE_HELD_FOR = timedelta(days=90)

# anything that is, or might become, a top-level route
RESERVED = {
    "about", "account", "admin", "album", "albums", "api", "auth", "blog",
    "contact", "cosign", "dashboard", "delete", "discord", "download", "explore",
    "export", "feed", "follow", "following", "followers", "help", "home", "link",
    "login", "logout", "me", "moderation", "new", "rateify", "notifications",
    "oauth", "press", "privacy", "profile", "register", "reset", "root",
    "search", "settings", "signin", "signup", "static", "status", "support",
    "terms", "track", "tracks", "u", "user", "users", "verify", "welcome", "www",
}


class HandleError(Exception):
    """Rejected for a reason we can safely say out loud."""


def normalize(handle):
    return (handle or "").strip().lstrip("@").casefold()


def validate(handle):
    """Check the shape of a handle. Returns the casefolded form."""
    ci = normalize(handle)
    if not HANDLE_RE.match(ci):
        raise HandleError(
            "handles are 3-20 characters, using letters, numbers and underscores"
        )
    if ci in RESERVED:
        raise HandleError("that one's reserved")
    return ci


def is_available(session, handle, for_user=None):
    ci = validate(handle)
    taken = session.scalar(select(User).where(User.handle_ci == ci))
    if taken is None:
        return True
    if for_user is not None and taken.id == for_user.id:
        return True
    # a handle released less than 90 days ago is still held by its old owner
    return False


def claim(session, user, handle):
    """Take a handle, or explain why not."""
    ci = validate(handle)

    if user.handle_ci == ci:
        user.handle = handle.strip().lstrip("@")  # a pure casing change is free
        return user

    if user.handle_changed_at is not None:
        changed = user.handle_changed_at
        if changed.tzinfo is None:  # SQLite
            from datetime import timezone

            changed = changed.replace(tzinfo=timezone.utc)
        if utcnow() - changed < RENAME_EVERY:
            days = (RENAME_EVERY - (utcnow() - changed)).days + 1
            raise HandleError(f"you can change your handle again in {days} days")

    if not is_available(session, ci, for_user=user):
        raise HandleError("that one's taken")

    user.handle = handle.strip().lstrip("@")
    user.handle_ci = ci
    user.handle_changed_at = utcnow()
    session.flush()
    return user


def suggest(session, base):
    """A handle near the one they wanted, for when it's gone."""
    stem = re.sub(r"[^a-z0-9_]", "", normalize(base))[:16] or "listener"
    if len(stem) < 3:
        stem = (stem + "___")[:3]
    for suffix in ("", *(str(n) for n in range(2, 100))):
        candidate = f"{stem}{suffix}"
        try:
            if is_available(session, candidate):
                return candidate
        except HandleError:
            continue
    return None
