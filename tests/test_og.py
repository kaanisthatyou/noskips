"""Link preview cards.

The unfurl is the product's first impression in a Discord channel, so these
check the cards actually render — and, more importantly, that they respect the
same privacy rules as the pages they preview. A private shelf whose OG card
still shows the numbers would leak exactly what the toggle promised to hide.
"""

import io

import pytest

from tests.test_api import rate, signup
from tests.test_pages import album_key_of

pytest.importorskip("PIL", reason="pillow not installed; cards degrade to no og:image")

from PIL import Image  # noqa: E402


def open_png(response):
    assert response.mimetype == "image/png"
    return Image.open(io.BytesIO(response.data))


def test_profile_card_renders(client):
    signup(client)
    rate(client, 8.0)

    image = open_png(client.get("/og/u/kaan.png"))

    assert image.size == (1200, 630)


def test_album_card_renders(client):
    signup(client)
    rate(client, 9.0)

    image = open_png(client.get(f"/og/album/{album_key_of(client)}.png"))

    assert image.size == (1200, 630)


def test_a_long_album_title_still_fits(client):
    """Titles vary wildly; a card that runs off its own edge looks broken."""
    signup(client)
    client.post("/v1/sync", json={"ops": [{
        "op": "rate",
        "artist": "Godspeed You! Black Emperor",
        "album": "Lift Your Skinny Fists Like Antennas To Heaven And Then Some More Words",
        "title": "Storm", "value": 9.0, "label": "9",
    }]})

    r = client.get(f"/og/album/{album_key_of(client)}.png")

    assert r.status_code == 200
    assert open_png(r).size == (1200, 630)


def test_no_card_for_a_song_nobody_rated(client):
    assert client.get("/og/album/nothinghere00000000.png").status_code == 404
    assert client.get("/og/u/nobody.png").status_code == 404


def test_a_private_shelf_has_no_card(client, app):
    """Otherwise the preview leaks exactly what the toggle promised to hide."""
    signup(client)
    rate(client, 8.0)
    client.patch("/v1/me", json={"is_private": True})

    assert app.test_client().get("/og/u/kaan.png").status_code == 404


def test_pages_advertise_their_cards(client):
    signup(client)
    rate(client, 8.0)

    assert b'property="og:image"' in client.get("/@kaan").data
    assert b"/og/u/kaan.png" in client.get("/@kaan").data


def test_a_private_page_advertises_no_card(client, app):
    signup(client)
    rate(client, 8.0)
    client.patch("/v1/me", json={"is_private": True})

    assert b'property="og:image"' not in app.test_client().get("/@kaan").data
