"""Track identity — turning the Windows media session's raw strings into a key
that two strangers on two machines will agree on.

This is the load-bearing module of the whole social layer. SMTC hands us
whatever Spotify put in the tags, and the *same song* arrives as:

    Tame Impala / Currents            / Let It Happen
    Tame Impala / Currents (Deluxe)   / Let It Happen - 2015 Remaster
    Tame Impala / Currents [Explicit] / Let It Happen

Key the shared index on those raw strings and it shatters into thousands of
singleton works, every community average is computed over one person, and the
social layer is worthless. So we normalize hard — but only in the directions
that are always safe.

Two keys come out of here:

  * ``work_key``  — artist + title. Deliberately **not** album: people rate the
    song, and a track that appears on a single, an album and a greatest-hits
    should collect one pile of verdicts rather than three.
  * ``album_key`` — artist + album, used only for grouping the shelf and the
    album pages.

The hard-won rule about what we *don't* touch: edition noise (remaster, deluxe,
explicit) describes the same performance and gets stripped. ``live``,
``acoustic``, ``demo``, ``remix`` and the like describe a *different*
performance and are load-bearing — strip those and you'd merge Nirvana's
Unplugged into Nevermind.

Everything here is pure and deterministic: same strings in, same keys out, on
any machine, forever. Changing a rule silently re-keys the world, so treat the
fixture table in tests/test_resolve.py as the specification.
"""

import base64
import hashlib
import re
import unicodedata
from dataclasses import dataclass

# unit separator: cannot appear in a media tag, so the joined key is unambiguous
SEP = "\x1f"

KEY_LEN = 20

# ---------------------------------------------------------------- cleanup ----

# Characters that differ between tag sources but never carry meaning. Spelled
# as escapes on purpose — these are exactly the characters you cannot trust an
# editor, a terminal or a diff to round-trip.
_PUNCT_MAP = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",   # curly singles
    "“": '"', "”": '"', "„": '"', "‟": '"',   # curly doubles
    "‐": "-", "‑": "-", "‒": "-", "–": "-",   # hyphens, en dash
    "—": "-", "―": "-", "−": "-",                  # em dash, bar, minus
    "…": "...",                                              # ellipsis
    " ": " ", " ": " ", " ": " ", "　": " ",   # hard spaces
}
_PUNCT_RE = re.compile("|".join(map(re.escape, _PUNCT_MAP)))

# zero-width junk that copy-paste and some taggers leave behind
_INVISIBLE_RE = re.compile("[​-‏⁠﻿]")

_WS_RE = re.compile(r"\s+")


def _fold_latin_accents(s):
    """Beyonce and Beyonce-with-an-acute are the same artist; ga and ka are not
    the same kana.

    So: decompose, drop combining marks *only* where the base character is
    ASCII, recompose. That folds Latin diacritics without touching Japanese
    dakuten, Korean jamo, or anything else where the mark carries the meaning.
    """
    out = []
    for ch in unicodedata.normalize("NFD", s):
        if unicodedata.combining(ch) and out and out[-1].isascii() and out[-1].isalpha():
            continue  # a diacritic sitting on a Latin letter — drop it
        out.append(ch)
    return unicodedata.normalize("NFC", "".join(out))


# ------------------------------------------------------- edition stripping ----

# Noise that means "same performance, different packaging". Longer alternatives
# come first so "super deluxe edition" wins over "deluxe".
_EDITION = r"""(?:
      (?:the\s+)?original\s+recording\s+remaster(?:ed)?
    | remaster(?:ed)?\s+\d{4}
    | (?:\d{4}\s+)?(?:digital\s+|analogue\s+|analog\s+)?remaster(?:ed)?(?:\s+version)?(?:\s+\d{4})?
    | super\s+deluxe(?:\s+(?:edition|version))?
    | deluxe(?:\s+(?:edition|version))?
    | expanded(?:\s+(?:edition|version))?
    | \d+(?:st|nd|rd|th)\s+anniversary(?:\s+(?:edition|version|remaster(?:ed)?))?
    | anniversary\s+(?:edition|version)
    | bonus\s+tracks?(?:\s+(?:edition|version))?
    | special\s+edition
    | collector'?s\s+edition
    | explicit(?:\s+version)?
    | clean(?:\s+version)?
    | mono(?:\s+version)?
    | stereo(?:\s+version)?
    | album\s+version
)"""

# ...but only where it is clearly packaging: inside brackets, or after " - " at
# the very end. A bare edition word mid-title is left alone.
_EDITION_BRACKETED = re.compile(
    r"\s*[\(\[]\s*" + _EDITION + r"\s*[\)\]]", re.IGNORECASE | re.VERBOSE
)
_EDITION_SUFFIX = re.compile(
    r"\s+-\s+" + _EDITION + r"\s*$", re.IGNORECASE | re.VERBOSE
)


def _strip_editions(s):
    """Remove edition noise, repeatedly — '(Deluxe) [2011 Remaster]' has two."""
    original = s
    for _ in range(4):  # bounded: pathological tags shouldn't spin forever
        stripped = _EDITION_SUFFIX.sub("", _EDITION_BRACKETED.sub("", s)).strip()
        if stripped == s:
            break
        s = stripped
    # never let normalization eat the whole string — an album genuinely called
    # "Mono" would otherwise normalize down to nothing
    return s or original


# -------------------------------------------------------------- featuring ----

_FEAT_BRACKETED = re.compile(
    r"\s*[\(\[]\s*(?:feat|ft|featuring)\.?\s+([^)\]]+?)\s*[\)\]]", re.IGNORECASE
)
_FEAT_SUFFIX = re.compile(
    r"\s+-\s+(?:feat|ft|featuring)\.?\s+(.+)$", re.IGNORECASE
)
_FEAT_SPLIT = re.compile(r"\s*(?:,|&|\band\b|\+)\s*")


def _split_feat(title):
    """Pull featured artists out of the title so 'Money Trees (feat. Jay Rock)'
    and 'Money Trees' land on the same work. The credits are kept, just moved."""
    feats = []

    def grab(m):
        feats.append(m.group(1).strip())
        return ""

    title = _FEAT_BRACKETED.sub(grab, title)
    title = _FEAT_SUFFIX.sub(grab, title)
    names = []
    for blob in feats:
        names.extend(p.strip() for p in _FEAT_SPLIT.split(blob) if p.strip())
    return title.strip(), tuple(names)


# --------------------------------------------------------------- normalize ----


def _clean(s):
    if not s:
        return ""
    s = unicodedata.normalize("NFKC", s)
    s = _INVISIBLE_RE.sub("", s)
    s = _PUNCT_RE.sub(lambda m: _PUNCT_MAP[m.group()], s)
    s = _fold_latin_accents(s)
    s = s.casefold()
    return _WS_RE.sub(" ", s).strip()


def _norm_artist(artist):
    s = _clean(artist)
    # taggers disagree on the separator for multi-artist tracks
    s = re.sub(r"\s*[;/]\s*", ", ", s)
    return re.sub(r"\s*,\s*", ", ", s)


def _hash(*parts):
    digest = hashlib.sha1(SEP.join(parts).encode("utf-8")).digest()
    return base64.b32encode(digest).decode("ascii").rstrip("=").lower()[:KEY_LEN]


@dataclass(frozen=True)
class Identity:
    """What a raw now-playing snapshot resolves to."""

    artist: str      # normalized
    album: str
    title: str
    feat: tuple      # featured artists lifted out of the title, normalized
    work_key: str    # artist + title — the song, across every release it's on
    album_key: str   # artist + album — the shelf grouping only


def identify(artist, album, title):
    """Normalize a now-playing snapshot into its shared identity."""
    norm_artist = _norm_artist(artist)
    norm_title, feats = _split_feat(_clean(title))
    norm_title = _strip_editions(norm_title)
    norm_album = _strip_editions(_clean(album))

    return Identity(
        artist=norm_artist,
        album=norm_album,
        title=norm_title,
        feat=tuple(_clean(f) for f in feats),
        work_key=_hash(norm_artist, norm_title),
        album_key=_hash(norm_artist, norm_album),
    )


def work_key(artist, title):
    """Shortcut when only the song key is wanted."""
    return identify(artist, "", title).work_key


def album_key(artist, album):
    """Shortcut when only the album grouping key is wanted."""
    return identify(artist, album, "").album_key
