"""Cover art, served through us so it can actually be cached.

We do not host artwork and this does not change that: nothing is written to
disk and nothing is written to the database. ``works.cover_url`` is a 60-odd
character string and always was — the whole column comes to a few kilobytes.
This is a pass-through with cache headers attached.

The reason it needs to exist is what Cover Art Archive answers with:

    GET /release-group/<mbid>/front-500
      307 -> archive.org           (no Cache-Control)
      302 -> the actual file       (no Cache-Control)
      200    image/jpeg 56 KB      (no Cache-Control, only ETag/Last-Modified)

Three round trips, about 2.3 seconds, and not one instruction telling the
browser it may keep the result. A shelf of sixty verdicts is 180 requests and
3.4 MB, on every single load, because heuristic caching is the browser's guess
rather than a promise.

So: one request to us, and a year of ``immutable``. A release group's front
cover is the definition of a thing that does not change — and if it ever does,
the MBID changes with it, so the URL is genuinely content-addressed.
"""

import requests
from flask import Response, abort, request

from . import bp

CAA_ROOT = "https://coverartarchive.org"
TIMEOUT = 10
# a year, and immutable: a re-listen of the same shelf costs the browser nothing
MAX_AGE = 31_536_000
# what a cover can plausibly weigh; anything past this is not a front-500
MAX_BYTES = 8 * 1024 * 1024

_MBID = 36  # canonical hyphenated form


def _looks_like_mbid(value):
    return (
        len(value) == _MBID
        and all(c in "0123456789abcdef-" for c in value.lower())
        and value.count("-") == 4
    )


@bp.get("/art/<mbid>/front.jpg")
def front(mbid):
    """One release group's front cover, with the headers CAA never sends.

    The filename on the end is not decoration: it gives the CDN, the browser
    and anyone who right-clicks a real extension to work with.
    """
    if not _looks_like_mbid(mbid):
        # never pass an arbitrary string upstream — this is a URL we construct
        abort(404)

    try:
        upstream = requests.get(
            f"{CAA_ROOT}/release-group/{mbid}/front-500",
            timeout=TIMEOUT,
            stream=True,
            headers={"User-Agent": _user_agent()},
        )
    except requests.RequestException:
        # the page shows its placeholder; a missing cover is not an error page
        abort(404)

    if upstream.status_code != 200:
        abort(404)

    content_type = upstream.headers.get("Content-Type", "image/jpeg")
    if not content_type.startswith("image/"):
        abort(404)

    body = upstream.raw.read(MAX_BYTES + 1, decode_content=True)
    if len(body) > MAX_BYTES:
        abort(404)

    response = Response(body, mimetype=content_type)
    response.headers["Cache-Control"] = f"public, max-age={MAX_AGE}, immutable"
    # Vercel's CDN reads this one, and keeping it separate means the edge can be
    # told something different from the browser later without touching the above
    response.headers["CDN-Cache-Control"] = f"public, max-age={MAX_AGE}, immutable"
    # lets a revalidating browser get a 304 instead of the bytes again
    etag = upstream.headers.get("ETag")
    if etag:
        response.headers["ETag"] = etag
        if request.headers.get("If-None-Match") == etag:
            return Response(status=304, headers=dict(response.headers))
    return response


def _user_agent():
    """The same contactable agent the resolver uses. Being rude to CAA gets the
    project blocked, not just one request."""
    from ..musicbrainz import USER_AGENT

    return USER_AGENT
