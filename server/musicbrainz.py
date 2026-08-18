"""Upgrading a fuzzy key into a real recording.

resolve.py gets two strangers to agree on a song most of the time, by
normalizing hard. This is the second pass that catches what normalization
can't: "Mr. Brightside" vs "Mister Brightside", a track credited to "Beyoncé"
on one release and "Beyonce Knowles" on another. MusicBrainz has already done
that work — it's free, needs no key, and gives us a stable recording MBID plus
a route to cover art.

Three rules this follows, in order of how badly they'd hurt to get wrong:

* **Resolution is never a gate.** A work with no MBID is a completely normal
  work. If MusicBrainz is down, slow, or simply doesn't know the song, nothing
  breaks and nobody notices.
* **Never on the write path.** A sync batch can carry 200 ops; at one request
  per second that would be a three-minute HTTP request. This runs from a cron
  instead, which is a deliberate departure from the original plan's
  "resolve inline with a 2s timeout".
* **One request per second, with a real User-Agent.** That's MusicBrainz's
  stated limit and the condition of using it. Being rude here gets the whole
  project blocked, not just one request.
"""

import os
import threading
import time

import requests
from sqlalchemy import func, select

from .models import Rating, Work
from .store import _aware

MB_ROOT = "https://musicbrainz.org/ws/2"
CAA_ROOT = "https://coverartarchive.org"
# `or`: a blank contact is exactly the rude User-Agent that gets the whole
# project blocked rather than one request. See server/db.py.
CONTACT = os.environ.get("MUSICBRAINZ_CONTACT") or "https://github.com/kaan/noskips"
USER_AGENT = f"noskips/2.0.0 ( {CONTACT} )"

MIN_SCORE = 88  # MusicBrainz's own confidence, 0-100
TIMEOUT = 8
_PACE = 1.05  # seconds between requests — their limit is 1/sec

_gate = threading.Lock()
_last_call = 0.0


def _throttled(method, url, **kwargs):
    """One request at a time, at most one per second, globally."""
    global _last_call
    with _gate:
        wait = _PACE - (time.monotonic() - _last_call)
        if wait > 0:
            time.sleep(wait)
        try:
            return requests.request(
                method, url, timeout=TIMEOUT,
                headers={"User-Agent": USER_AGENT}, **kwargs
            )
        finally:
            _last_call = time.monotonic()


# ------------------------------------------------------------------ lookup ----


def _escape(value):
    """Lucene special characters, which song titles are full of."""
    for char in r'\+-&|!(){}[]^"~*?:/':
        value = value.replace(char, f"\\{char}")
    return value


# What a release group has to be before its front cover may stand in for a song.
#
# This exists because of "Superhero (Heroes & Villains)", whose only release in
# MusicBrainz is *UK Official Singles Chart Top40, week of 2023-01-27* — a chart
# roundup whose sleeve is whoever was number one that week. Metro Boomin's track
# was therefore wearing a Taylor Swift cover. A chart, a DJ mix and a
# various-artists compilation all have artwork that says nothing about the song
# on it, so none of them may supply one.
_GOOD_PRIMARY = {"Album", "EP", "Single"}
_BAD_SECONDARY = {"Compilation", "DJ-mix", "Interview", "Audiobook", "Audio drama", "Spokenword"}


def _usable_group(group):
    """Is this release group's front cover honestly this song's cover?"""
    if not group or not group.get("id"):
        return False
    if group.get("primary-type") not in _GOOD_PRIMARY:
        return False
    return not (set(group.get("secondary-types") or []) & _BAD_SECONDARY)


def _edition_variants(album):
    """The album name, then the same name without an edition suffix.

    Players report "good kid, m.A.A.d city (Deluxe)" and MusicBrainz files the
    record as "good kid, m.A.A.d city" — the deluxe pressing is a release under
    the same group, not a group of its own. Searching the literal string finds
    nothing at all, so the parenthetical comes off for a second attempt.
    """
    album = (album or "").strip()
    if not album:
        return []
    variants = [album]
    for opener, closer in (("(", ")"), ("[", "]")):
        if album.endswith(closer) and opener in album:
            trimmed = album[: album.rindex(opener)].strip(" -–—")
            if trimmed and trimmed not in variants:
                variants.append(trimmed)
    return variants


def lookup_release_group(artist, album):
    """The release group for a named album, or None.

    Asked for by name because a recording's own release list often doesn't
    contain the record it came off — MusicBrainz knows that Superhero appeared
    on a chart compilation and, under that recording, nothing else. The album
    is a fact the widget already gave us, and it finds the right one first hit.
    """
    if not artist or not album:
        return None
    for candidate in _edition_variants(album):
        query = f'releasegroup:"{_escape(candidate)}" AND artist:"{_escape(artist)}"'
        try:
            response = _throttled(
                "GET", f"{MB_ROOT}/release-group",
                params={"query": query, "fmt": "json", "limit": 5},
            )
            response.raise_for_status()
            groups = response.json().get("release-groups") or []
        except (requests.RequestException, ValueError):
            return None

        for group in groups:
            if group.get("score", 0) < MIN_SCORE:
                continue
            if _usable_group(group):
                return group["id"]
    return None


def album_cover(session, work):
    """What the rest of this record already settled on, if anything.

    A song on an album wears the album's cover. Resolving that per track is
    both wasteful and wrong: seventeen tracks off *good kid, m.A.A.d city* went
    looking one at a time and came back with five different answers, among them
    a bootleg of a 2013 gig in Amsterdam and a 2024 concert film. Every one of
    those is a real release the song appears on, and not one of them is the
    record it belongs to.

    So the album decides once, keyed on album_key, and every track takes it.

    No flag is needed to tell an album-level cover from a track-level one: a
    work that has an album may only ever get its cover from an album match, so
    any cover found here is already the record's own. See resolve_work.
    """
    if not work.album_key:
        return None
    return session.scalar(
        select(Work.mbid_release_group)
        .where(
            Work.album_key == work.album_key,
            Work.id != work.id,
            Work.merged_into.is_(None),
            Work.mbid_release_group.is_not(None),
            Work.cover_url.is_not(None),
        )
        .limit(1)
    )


def lookup_recording(artist, title):
    """The best recording match, or None. Never raises."""
    if not artist or not title:
        return None
    query = f'recording:"{_escape(title)}" AND artist:"{_escape(artist)}"'
    try:
        response = _throttled(
            "GET", f"{MB_ROOT}/recording",
            params={"query": query, "fmt": "json", "limit": 3},
        )
        response.raise_for_status()
        recordings = response.json().get("recordings") or []
    except (requests.RequestException, ValueError):
        return None

    for item in recordings:
        if item.get("score", 0) < MIN_SCORE:
            continue
        # first *usable* one, not merely the first one — see _usable_group
        release_group = None
        for release in item.get("releases") or []:
            group = release.get("release-group") or {}
            if _usable_group(group):
                release_group = group["id"]
                break
        return {"recording": item["id"], "release_group": release_group}
    return None


def cover_url(release_group_mbid):
    """A Cover Art Archive URL, if art actually exists for this release group.

    Checked rather than assumed: storing a URL that 404s would put a broken
    image on every album page instead of the clean placeholder.

    Note this is a *link*, not a copy. We never host cover art — the widget's
    local cache is Spotify's artwork and uploading it isn't ours to do.
    """
    if not release_group_mbid:
        return None
    url = f"{CAA_ROOT}/release-group/{release_group_mbid}/front-500"
    try:
        response = _throttled("HEAD", url, allow_redirects=False)
    except requests.RequestException:
        return None
    # 307 is the usual answer: a redirect to the archive.org copy
    return url if response.status_code in (200, 301, 302, 307) else None


# ------------------------------------------------------------------ merging ----


def merge_works(session, loser, winner):
    """Fold one work into another once they turn out to be the same recording.

    The loser keeps its row and gains a `merged_into` pointer rather than being
    deleted, so every widget still holding the old key keeps resolving.
    """
    if loser.id == winner.id:
        return winner

    for rating in list(loser.ratings):
        clash = session.scalar(
            select(Rating).where(
                Rating.user_id == rating.user_id, Rating.work_id == winner.id
            )
        )
        if clash is None:
            rating.work_id = winner.id
            continue

        # The same person rated both spellings, and UNIQUE(user_id, work_id)
        # means only one row can survive. Note we *always* delete the loser's
        # row and transplant onto the survivor, rather than moving the loser's
        # row across and deleting the other: moving it first would put two rows
        # in the same slot for as long as it takes the flush to reach the
        # DELETE, which the database refuses outright.
        if _aware(rating.updated_at) > _aware(clash.updated_at):
            clash.value = rating.value
            clash.label = rating.label
            clash.note = rating.note
            clash.trace = rating.trace or clash.trace
            clash.is_public = rating.is_public
            clash.note_public = rating.note_public
            clash.provenance = rating.provenance
            clash.rev = max(rating.rev, clash.rev)
            clash.updated_at = rating.updated_at
        # whichever verdict wins, the credit belongs to the first time they
        # stamped this song under either spelling
        if _aware(rating.rated_at) < _aware(clash.rated_at):
            clash.rated_at = rating.rated_at
        session.delete(rating)
    session.flush()

    # recount from the ratings themselves rather than adding two denormalized
    # numbers together — after a merge with clashes they no longer agree
    winner.rating_count = session.scalar(
        select(func.count()).select_from(Rating).where(Rating.work_id == winner.id)
    )
    winner.rating_sum = session.scalar(
        select(func.coalesce(func.sum(Rating.value), 0)).where(Rating.work_id == winner.id)
    )
    loser.rating_count = 0
    loser.rating_sum = 0
    loser.merged_into = winner.id
    loser.pending_resolution = False
    session.flush()
    return winner


# ----------------------------------------------------------------- the drain ----


def resolve_work(session, work):
    """Resolve one work. Returns True if anything changed."""
    work.pending_resolution = False  # attempted; don't spin on it forever
    match = lookup_recording(work.display_artist, work.display_title)

    # Cover art is decided by the album, not by the track.
    #
    # It does not depend on the recording matching, so it is worked out either
    # way: titles are where the mess lives — "Too Many Nights (feat. Don
    # Toliver & with Future)" matches nothing — while the record it came off is
    # usually a clean, famous name that matches on the first hit.
    #
    # And it is asked of the album rather than the recording because a
    # recording's release list is whatever MusicBrainz happens to hold: a
    # chart roundup, a mixtape, a live bootleg. The album is what the person
    # actually put on.
    #
    # First for free, from whatever the rest of this record already settled on.
    group = album_cover(session, work)
    if group is None:
        group = lookup_release_group(work.display_artist, work.display_album)

    if group is None and not (work.display_album or "").strip():
        # A single has no album to defer to, so its own release group is the
        # only thing there is. A track that DOES name an album never falls back
        # to one: that is how "Money Trees" ended up wearing the sleeve of a
        # bootleg from Amsterdam, which is a real release it appears on and is
        # not the record anybody was listening to.
        group = match["release_group"] if match else None

    if match is None and group is None:
        session.flush()
        return False

    if match is not None:
        work.mbid_recording = match["recording"]
    work.mbid_release_group = group

    if work.mbid_release_group and not work.cover_url:
        work.cover_url = cover_url(work.mbid_release_group)
    session.flush()

    if match is None:
        # no recording, so nothing to merge on — a cover is all this pass gets
        return True

    twin = session.scalar(
        select(Work).where(
            Work.mbid_recording == work.mbid_recording,
            Work.id != work.id,
            Work.merged_into.is_(None),
        )
    )
    if twin is not None:
        # the older row wins, so the first press stays with whoever got there first
        older, newer = (twin, work) if twin.created_at <= work.created_at else (work, twin)
        merge_works(session, newer, older)
    return True


def resolve_pending(session, limit=20):
    """Work through the backlog. Returns a small summary for the caller to log."""
    works = session.scalars(
        select(Work)
        .where(Work.pending_resolution.is_(True), Work.merged_into.is_(None))
        .order_by(Work.created_at)
        .limit(limit)
    ).all()

    resolved = 0
    for work in works:
        try:
            if resolve_work(session, work):
                resolved += 1
        except Exception:
            # one bad row must not stop the queue; it's already marked attempted
            continue
    return {"attempted": len(works), "resolved": resolved}
