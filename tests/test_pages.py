"""The rendered pages.

Templates fail at render time, not import time, so every page gets walked here.
The assertions lean on privacy and on the one rule — an album nobody has rated
must 404 rather than render an empty shell.
"""

from tests.test_api import SONG, rate, signup


def album_key_of(client):
    return client.get("/v1/u/kaan/shelf").get_json()["verdicts"][0]["work"]["album_key"]


# ------------------------------------------------------------------ basics ----


def test_landing_page_renders_for_a_stranger(client):
    r = client.get("/")
    assert r.status_code == 200
    assert b"judge every song" in r.data


def test_landing_page_sends_a_signed_in_user_to_their_shelf(client):
    signup(client)
    r = client.get("/")
    assert r.status_code == 302 and r.headers["Location"] == "/@kaan"


def test_a_new_account_is_pushed_to_claim_a_name(client):
    signup(client, handle=None)
    r = client.get("/")
    assert r.status_code == 302 and r.headers["Location"] == "/welcome"
    assert b"claim your name" in client.get("/welcome").data


def test_login_and_signup_pages_render(client):
    assert b"sign in" in client.get("/login").data
    assert b"start a shelf" in client.get("/signup").data


def test_the_widget_stylesheet_and_fonts_are_served(client):
    """The web has to be visibly the same object as the widget, which means the
    same font files, not a lookalike."""
    assert client.get("/static/zine.css").status_code == 200
    assert client.get("/static/fonts/SpecialElite.ttf").status_code == 200
    assert client.get("/static/web.js").status_code == 200


# ----------------------------------------------------------------- profile ----


def test_profile_shows_stamps_and_first_presses(client):
    signup(client)
    rate(client, 8.0, note="a real banger")

    body = client.get("/@kaan").data.decode()

    assert "@kaan" in body
    assert "FIRST PRESSES" in body
    assert "a real banger" in body
    assert "Let It Happen" in body


def test_a_trace_renders_as_a_waveform(client):
    """The whole point of the trace: it travels. Widget → server → page."""
    import base64

    from audio import TRACE_POINTS

    trace = base64.b64encode(bytes(range(256))[:TRACE_POINTS]).decode()
    signup(client)
    rate(client, 8.0, trace=trace)

    body = client.get("/@kaan").data.decode()

    assert "trace-line" in body
    # a real coordinate list, not an empty points attribute
    assert '<polyline points="0.00,' in body
    assert body.count(",") > 200


def test_a_verdict_without_a_trace_draws_nothing(client):
    """No capture, no trace — and no empty svg pretending there was one."""
    signup(client)
    rate(client, 8.0)

    assert "trace-line" not in client.get("/@kaan").data.decode()


def test_unknown_handle_is_a_404_page(client):
    r = client.get("/@nobody")
    assert r.status_code == 404
    assert b"be the first press" in r.data


def test_a_private_shelf_shows_nothing_to_a_stranger(client, app):
    signup(client)
    rate(client, 8.0, note="my secret shame")
    client.patch("/v1/me", json={"is_private": True})

    body = app.test_client().get("/@kaan").data.decode()

    assert "this shelf is private" in body
    assert "my secret shame" not in body


def test_a_private_note_is_not_in_the_html(client, app):
    """Privacy has to hold in the rendered page, not just in the JSON."""
    signup(client)
    rate(client, 8.0, note="nobody should read this", note_public=False)

    body = app.test_client().get("/@kaan").data.decode()

    assert "nobody should read this" not in body
    assert "note kept private" in body


def test_your_own_private_note_is_visible_to_you(client):
    signup(client)
    rate(client, 8.0, note="just for me", note_public=False)

    assert "just for me" in client.get("/@kaan").data.decode()


def test_a_non_public_verdict_is_absent_for_strangers(client, app):
    signup(client)
    rate(client, 8.0, is_public=False)

    assert "Let It Happen" not in app.test_client().get("/@kaan").data.decode()


# ------------------------------------------------------------------- album ----


def test_album_page_renders_with_a_histogram(client):
    signup(client)
    rate(client, 9.0)

    body = client.get(f"/album/{album_key_of(client)}").data.decode()

    assert "Currents" in body
    assert "Tame Impala" in body
    assert "histogram" in body
    assert "9.0" in body


def test_an_album_nobody_rated_has_no_page(client):
    """The one rule, as HTTP: no verdicts, no page."""
    assert client.get("/album/nothinghere00000000").status_code == 404


def test_the_album_page_disappears_again_when_the_last_verdict_goes(client):
    signup(client)
    rate(client, 9.0)
    key = album_key_of(client)
    assert client.get(f"/album/{key}").status_code == 200

    client.post("/v1/sync", json={"ops": [{"op": "unrate", **SONG}]})

    assert client.get(f"/album/{key}").status_code == 404


def test_certified_noskips_needs_more_than_one_great_track(client):
    signup(client)
    rate(client, 10.0)
    body = client.get(f"/album/{album_key_of(client)}").data.decode()
    assert "CERTIFIED NO-SKIPS" not in body

    for title in ["Eventually", "The Less I Know The Better", "Yes I'm Changing"]:
        client.post(
            "/v1/sync",
            json={"ops": [{"op": "rate", "artist": "Tame Impala", "album": "Currents",
                           "title": title, "value": 10.0, "label": "10"}]},
        )

    assert "CERTIFIED NO-SKIPS" in client.get(f"/album/{album_key_of(client)}").data.decode()


# -------------------------------------------------------------------- feed ----


def test_feed_requires_signing_in(client):
    r = client.get("/feed")
    assert r.status_code == 302 and "/login" in r.headers["Location"]


def test_feed_shows_people_you_follow(client, app):
    signup(client)
    rate(client, 8.0, note="listen to this")

    follower = app.test_client()
    signup(follower, email="mert@example.com", handle="mert")
    follower.post("/v1/follow/kaan")

    body = follower.get("/feed").data.decode()
    assert "listen to this" in body
    assert "@kaan" in body


def test_an_empty_feed_says_so(client):
    signup(client)
    assert b"quiet in here" in client.get("/feed").data


# ---------------------------------------------------------------- settings ----


def test_settings_lists_linked_devices(client, app):
    signup(client)
    started = client.post(
        "/v1/pair/start", json={"device_nonce": "n" * 32, "device_name": "kaans thinkpad"}
    ).get_json()
    client.post("/link", data={"code": started["code"].replace("-", "")})

    body = client.get("/settings").data.decode()
    assert "kaans thinkpad" in body
    assert "linked devices" in body


def test_attacker_controlled_strings_are_escaped(client, app):
    """Device names and display names come from users. Every one of them is
    rendered through Jinja's autoescaping, and this is the test that notices if
    someone ever reaches for |safe."""
    signup(client)
    client.post(
        "/v1/pair/start",
        json={"device_nonce": "n" * 32, "device_name": "<script>alert(1)</script>"},
    )
    client.patch("/v1/me", json={"display_name": "<img src=x onerror=alert(1)>"})
    rate(client, 8.0, note="<script>steal()</script>")

    for path in ("/settings", "/@kaan"):
        body = client.get(path).data.decode()
        assert "<script>alert(1)</script>" not in body
        assert "<img src=x onerror" not in body
        assert "<script>steal()</script>" not in body


def test_a_device_can_be_unlinked_from_the_web(client, app):
    """Specifically so a lost machine can be cut off from an account."""
    signup(client)
    started = client.post("/v1/pair/start", json={"device_nonce": "n" * 32}).get_json()
    client.post("/link", data={"code": started["code"].replace("-", "")})

    widget = app.test_client()
    token = widget.post(
        "/v1/pair/poll", json={"device_nonce": "n" * 32}
    ).get_json()["device_token"]
    device_id = widget.get(
        "/v1/me", headers={"Authorization": f"Bearer {token}"}
    ).get_json()["me"]["device"]["id"]

    assert client.delete(f"/v1/devices/{device_id}").status_code == 200
    assert widget.get("/v1/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_you_cannot_unlink_somebody_elses_device(client, app):
    signup(client)
    started = client.post("/v1/pair/start", json={"device_nonce": "n" * 32}).get_json()
    client.post("/link", data={"code": started["code"].replace("-", "")})
    widget = app.test_client()
    token = widget.post("/v1/pair/poll", json={"device_nonce": "n" * 32}).get_json()["device_token"]
    device_id = widget.get(
        "/v1/me", headers={"Authorization": f"Bearer {token}"}
    ).get_json()["me"]["device"]["id"]

    attacker = app.test_client()
    signup(attacker, email="mert@example.com", handle="mert")

    assert attacker.delete(f"/v1/devices/{device_id}").status_code == 404


# -------------------------------------------------------------------- link ----


def test_the_link_page_warns_about_the_phishing_case(client):
    signup(client)
    started = client.post("/v1/pair/start", json={"device_nonce": "n" * 32}).get_json()

    body = client.get(f"/link?code={started['code']}").data.decode()

    assert "link this device?" in body
    assert "only continue if you" in body


def test_an_expired_or_bogus_code_explains_itself(client):
    signup(client)
    assert b"that didn't work" in client.get("/link?code=ZZZZZZ").data
