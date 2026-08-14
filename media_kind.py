"""Telling a song from a video.

The widget reads the Windows media session, which happily reports *anything*
playing — a Spotify track, a YouTube video, a podcast, a Twitch stream. For an
app whose whole premise is judging songs, "Minecraft parkour compilation #47"
landing on your shelf is a bug, and it landing in the shared index is worse.

Windows already knows the answer. `MediaPlaybackType` comes straight off the
session as MUSIC, VIDEO, IMAGE or UNKNOWN, and it needs no guessing:

    Spotify.exe -> MediaPlaybackType.MUSIC   (verified)

The catch is that reading it requires the winrt-Windows.Media package, which
defines the enum. Without it the attribute exists but raises on access — which
is exactly what it did here before it was added to requirements.txt, and why
this module treats a failed read as "unknown" rather than an error.

Plenty of sources report UNKNOWN (browsers are inconsistent, and some players
never set it at all), so there's a fallback below. The fallback is deliberately
conservative: it only claims "video" when it has real evidence, because wrongly
filtering out somebody's music is a worse failure than letting a video through.
"""

MUSIC = "music"
VIDEO = "video"
IMAGE = "image"
UNKNOWN = "unknown"

_BY_VALUE = {0: UNKNOWN, 1: MUSIC, 2: VIDEO, 3: IMAGE}

# Browsers, which is where videos come from. Firefox reports a CLSID rather
# than an exe name, hence the odd one out.
BROWSER_HINTS = (
    "chrome", "msedge", "firefox", "opera", "brave", "vivaldi", "librewolf",
    "308046b0af4a39cb",
)


def _reported(info, playback_info=None):
    """What the session says it is, if it says anything.

    Both the media properties and the playback info carry the field, and
    different apps populate different ones, so we take whichever answers.
    """
    for source in (info, playback_info):
        if source is None:
            continue
        try:
            value = source.playback_type
        except Exception:
            continue  # the enum package is missing; fall through to the guess
        if value is None:
            continue
        raw = getattr(value, "value", value)
        try:
            return _BY_VALUE.get(int(raw), UNKNOWN)
        except (TypeError, ValueError):
            continue
    return None


def classify(info, playback_info=None, source_app="", album="", artist=""):
    """The kind of thing that's playing: music, video, image or unknown."""
    reported = _reported(info, playback_info)
    if reported is not None and reported != UNKNOWN:
        return reported

    # Nothing reported. Guess, but only where the evidence is decent.
    app = (source_app or "").lower()
    is_browser = any(hint in app for hint in BROWSER_HINTS)

    # Album *and* artist together is the shape of a music library entry; media
    # players fill both in and video sites essentially never do.
    if album and artist:
        return MUSIC
    if is_browser and not album:
        # a browser playing something with no album is a video far more often
        # than not — but see accepts() for why this stays a soft signal
        return VIDEO
    return UNKNOWN


def store_for(kind):
    """Which shelf a verdict belongs on.

    Nothing is ever turned away — a video is rated exactly like a song. It just
    lands in its own file, which is what keeps it off the shared index: the
    sync engine is only ever handed the music store, so this one function is
    the entire boundary between "yours" and "everyone's".

    UNKNOWN counts as music on purpose. A player that doesn't announce itself
    is far more likely to be a music player than a video one, and the cost of
    guessing wrong is one entry on the wrong shelf.
    """
    return VIDEO if kind == VIDEO else MUSIC
