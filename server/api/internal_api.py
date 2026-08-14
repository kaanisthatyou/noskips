"""Jobs that run on a timer rather than for a person.

Vercel's Hobby plan only fires cron once a day, which is far too slow to work
through a resolution backlog. So this is an ordinary token-protected endpoint
and GitHub Actions calls it every fifteen minutes — also free, and it keeps the
schedule in the repo where you can see it.
"""

import hmac
import os

from flask import g, jsonify, request

from .. import musicbrainz
from ..security import ApiError, prune_rate_limits
from . import bp


def _authorized():
    """Constant-time compare, because this is a bearer secret in a header."""
    expected = os.environ.get("RESOLVER_TOKEN", "")
    if not expected:
        return False
    header = request.headers.get("Authorization", "")
    supplied = header[7:].strip() if header.lower().startswith("bearer ") else ""
    return hmac.compare_digest(supplied, expected)


@bp.post("/internal/resolve")
def resolve():
    """Work through the MusicBrainz backlog.

    Deliberately bounded per call: at one request per second, twenty works is
    about twenty seconds, which sits comfortably inside a serverless timeout.
    The next tick picks up where this one stopped.
    """
    if not _authorized():
        # 404 rather than 401 — an endpoint nobody should know about shouldn't
        # confirm it exists to someone guessing
        raise ApiError("not found", 404, "not_found")

    limit = min(int(request.args.get("limit", 20)), 50)
    # the one timer this project has, so it also carries the housekeeping:
    # spent rate-limit windows are keyed by IP and have no business persisting
    pruned = prune_rate_limits(g.db)
    return jsonify(ok=True, pruned_rate_limits=pruned, **musicbrainz.resolve_pending(g.db, limit=limit))
