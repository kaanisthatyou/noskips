"""The specification for track identity.

Each MERGE case is a pair of raw SMTC snapshots that *must* collapse to one
work_key; each SPLIT case is a pair that must stay apart. Adding a rule to
resolve.py without adding a case here is how the shared index quietly rots.
"""

import pytest

from server.resolve import album_key, identify, work_key

# Pairs that describe the same performance in different packaging.
MERGE = [
    (
        "deluxe album + remastered title",
        ("Tame Impala", "Currents", "Let It Happen"),
        ("Tame Impala", "Currents (Deluxe)", "Let It Happen - 2015 Remaster"),
    ),
    (
        "explicit tag on the album",
        ("Kendrick Lamar", "DAMN.", "HUMBLE."),
        ("Kendrick Lamar", "DAMN. [Explicit]", "HUMBLE."),
    ),
    (
        "featured artist lifted out of the title",
        ("Kendrick Lamar", "good kid, m.A.A.d city", "Money Trees"),
        ("Kendrick Lamar", "good kid, m.A.A.d city", "Money Trees (feat. Jay Rock)"),
    ),
    (
        "feat. as a dash suffix",
        ("Drake", "Views", "Too Good"),
        ("Drake", "Views", "Too Good - feat. Rihanna"),
    ),
    (
        "curly vs straight apostrophe",
        ("Beyonce", "Lemonade", "Don't Hurt Yourself"),
        ("Beyoncé", "Lemonade", "Don’t Hurt Yourself"),
    ),
    (
        "em dash vs hyphen before edition noise",
        ("Radiohead", "OK Computer", "Karma Police — 2017 Remaster"),
        ("Radiohead", "OK Computer", "Karma Police - 2017 Remaster"),
    ),
    (
        "same song, different releases (album vs greatest hits)",
        ("Fleetwood Mac", "Rumours", "Dreams"),
        ("Fleetwood Mac", "50 Years - Don't Stop", "Dreams"),
    ),
    (
        "super deluxe + bonus track noise",
        ("The Beatles", "Abbey Road", "Come Together"),
        ("The Beatles", "Abbey Road (Super Deluxe Edition)", "Come Together"),
    ),
    (
        "zero-width space and non-breaking space",
        ("Sigur Ros", "Takk...", "Hoppipolla"),
        ("Sigur Rós", "Takk...", "Hopp​ipolla"),
    ),
    (
        "multi-artist separator disagreement",
        ("Silk Sonic; Bruno Mars", "An Evening", "Leave The Door Open"),
        ("Silk Sonic, Bruno Mars", "An Evening", "Leave The Door Open"),
    ),
    (
        "case and stray whitespace",
        ("MF DOOM", "MM..FOOD", "Rapp Snitch Knishes"),
        ("mf doom", "MM..FOOD", "  Rapp   Snitch Knishes "),
    ),
    (
        "mono/stereo packaging",
        ("The Beach Boys", "Pet Sounds", "God Only Knows"),
        ("The Beach Boys", "Pet Sounds (Mono)", "God Only Knows (Stereo)"),
    ),
]

# Pairs that describe genuinely different performances. Merging any of these
# would be worse than fragmenting — it puts verdicts on the wrong recording.
SPLIT = [
    (
        "studio vs live",
        ("Nirvana", "Nevermind", "Come As You Are"),
        ("Nirvana", "MTV Unplugged In New York", "Come As You Are (Live)"),
    ),
    (
        "studio vs acoustic",
        ("Radiohead", "The Bends", "Fake Plastic Trees"),
        ("Radiohead", "The Bends", "Fake Plastic Trees (Acoustic)"),
    ),
    (
        "studio vs demo",
        ("Bruce Springsteen", "Nebraska", "Born In The U.S.A."),
        ("Bruce Springsteen", "Nebraska", "Born In The U.S.A. - Demo"),
    ),
    (
        "original vs remix",
        ("Daft Punk", "Discovery", "Harder Better Faster Stronger"),
        ("Daft Punk", "Discovery", "Harder Better Faster Stronger (Remix)"),
    ),
    (
        "re-recording keeps its marker",
        ("Taylor Swift", "Fearless", "Love Story"),
        ("Taylor Swift", "Fearless (Taylor's Version)", "Love Story (Taylor's Version)"),
    ),
    (
        "different artists, same title",
        ("Johnny Cash", "American IV", "Hurt"),
        ("Nine Inch Nails", "The Downward Spiral", "Hurt"),
    ),
    (
        "radio edit is a different cut",
        ("New Order", "Substance", "Blue Monday"),
        ("New Order", "Substance", "Blue Monday (Radio Edit)"),
    ),
]


@pytest.mark.parametrize("name,a,b", MERGE, ids=[c[0] for c in MERGE])
def test_merges(name, a, b):
    assert work_key(a[0], a[2]) == work_key(b[0], b[2])


@pytest.mark.parametrize("name,a,b", SPLIT, ids=[c[0] for c in SPLIT])
def test_stays_apart(name, a, b):
    assert work_key(a[0], a[2]) != work_key(b[0], b[2])


# --------------------------------------------------------------- album keys ----


@pytest.mark.parametrize(
    "left,right",
    [
        ("Currents", "Currents (Deluxe)"),
        ("DAMN.", "DAMN. [Explicit]"),
        ("Abbey Road", "Abbey Road - 2019 Remaster"),
        ("Blonde", "Blonde (Special Edition)"),
    ],
)
def test_album_editions_group_together(left, right):
    assert album_key("x", left) == album_key("x", right)


@pytest.mark.parametrize(
    "left,right",
    [
        ("Nevermind", "MTV Unplugged In New York"),
        ("Fearless", "Fearless (Taylor's Version)"),
        ("Kid A", "Kid A Mnesia"),
    ],
)
def test_different_albums_stay_apart(left, right):
    assert album_key("x", left) != album_key("x", right)


# ----------------------------------------------------------------- details ----


def test_dakuten_is_not_an_accent():
    """NFD-stripping combining marks would turn ga into ka. Japanese titles must
    survive normalization untouched."""
    got = identify("ずっと真夜中でいいのに。", "", "秒針を噛む")
    assert got.title == "秒針を噛む"
    assert identify("x", "", "が").title != identify("x", "", "か").title


def test_feat_credits_are_kept_not_discarded():
    got = identify("Calvin Harris", "Motion", "Outside (feat. Ellie Goulding)")
    assert got.title == "outside"
    assert got.feat == ("ellie goulding",)


def test_multiple_featured_artists_split():
    got = identify("Metro Boomin", "Heroes & Villains", "Creepin' (feat. The Weeknd & 21 Savage)")
    assert set(got.feat) == {"the weeknd", "21 savage"}


def test_normalization_never_empties_a_title():
    """An album genuinely called 'Mono' must not normalize away to nothing."""
    assert identify("Mono", "Mono", "Mono").album == "mono"


def test_keys_are_url_safe_and_fixed_length():
    key = work_key("Tame Impala", "Let It Happen")
    assert len(key) == 20
    assert key.isalnum() and key.islower()


def test_identify_is_deterministic():
    a = identify("Aphex Twin", "Selected Ambient Works 85-92", "Xtal")
    b = identify("Aphex Twin", "Selected Ambient Works 85-92", "Xtal")
    assert a == b


def test_edition_word_mid_title_is_left_alone():
    """'Clean' and 'Mono' are real words. Only bracketed/suffixed noise goes."""
    assert identify("x", "", "Clean Up Woman").title == "clean up woman"
    assert identify("x", "", "Mono No Aware").title == "mono no aware"
