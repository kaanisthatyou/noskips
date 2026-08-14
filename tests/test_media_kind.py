"""Telling a song from a video.

Nothing gets turned away: a video is rated exactly like a song, it just lands
on its own shelf and never reaches the shared index. So the classifier's job
isn't gatekeeping, it's filing — and its failure modes are asymmetric. Filing a
video under music costs one wrong entry; filing somebody's music under videos
silently keeps it off their profile. When in doubt it says music.
"""

import pytest

from media_kind import IMAGE, MUSIC, UNKNOWN, VIDEO, classify, store_for


class FakeProps:
    """Stands in for SMTC media properties."""

    def __init__(self, playback_type="missing"):
        if playback_type != "missing":
            self.playback_type = playback_type

    def __getattr__(self, name):
        # matches the real thing when winrt-Windows.Media is absent: the
        # attribute exists but blows up on access
        if name == "playback_type":
            raise AttributeError("no attribute 'MediaPlaybackType'")
        raise AttributeError(name)


class FakeEnum:
    """A winrt enum member, which carries its number on `.value`."""

    def __init__(self, value):
        self.value = value


# ------------------------------------------------------- what windows says ----


def test_music_is_recognised():
    """Verified against the real thing: Spotify.exe reports MUSIC."""
    assert classify(FakeProps(FakeEnum(1))) == MUSIC


def test_video_is_recognised():
    assert classify(FakeProps(FakeEnum(2))) == VIDEO


def test_a_plain_integer_works_too():
    """Not every projection wraps the value in an enum object."""
    assert classify(FakeProps(2)) == VIDEO


def test_the_playback_info_is_consulted_when_properties_are_silent():
    """Apps populate one or the other; either will do."""
    assert classify(FakeProps(None), FakeProps(FakeEnum(2))) == VIDEO


def test_a_missing_winrt_enum_package_does_not_raise():
    """This is the real-world case that started all of this: without
    winrt-Windows.Media the attribute raises on access."""
    assert classify(FakeProps(), source_app="Spotify.exe") == UNKNOWN


# ------------------------------------------------------------- the fallback ----


def test_album_and_artist_together_read_as_music():
    assert classify(
        FakeProps(FakeEnum(0)), source_app="foobar2000.exe",
        album="Currents", artist="Tame Impala",
    ) == MUSIC


def test_a_browser_with_no_album_reads_as_video():
    for browser in ("chrome.exe", "msedge.exe", "308046B0AF4A39CB"):
        assert classify(
            FakeProps(FakeEnum(0)), source_app=browser,
            album="", artist="Some Channel",
        ) == VIDEO


def test_a_browser_playing_something_with_an_album_is_still_music():
    """YouTube Music and web players fill the album in; they must not be
    mistaken for videos just because they run in a browser."""
    assert classify(
        FakeProps(FakeEnum(0)), source_app="chrome.exe",
        album="Currents", artist="Tame Impala",
    ) == MUSIC


def test_an_unknown_player_stays_unknown_rather_than_guessing():
    assert classify(FakeProps(FakeEnum(0)), source_app="vlc.exe", album="", artist="") == UNKNOWN


def test_what_windows_says_beats_the_guess():
    """An explicit MUSIC must survive a browser source and a missing album."""
    assert classify(
        FakeProps(FakeEnum(1)), source_app="chrome.exe", album="", artist="",
    ) == MUSIC


# ------------------------------------------------------------- which shelf ----


def test_videos_go_to_the_videos_shelf():
    assert store_for(VIDEO) == VIDEO


@pytest.mark.parametrize("kind", [MUSIC, UNKNOWN, IMAGE, "", None])
def test_everything_else_is_music(kind):
    """Including unknown: a player that doesn't announce itself is far more
    likely to be a music player, and the shared index tolerates that better
    than a song going missing would."""
    assert store_for(kind) == MUSIC
