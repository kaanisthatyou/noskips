"""End-to-end tests through the real Flask app.

These exercise the seams the unit tests can't: session cookies, device tokens,
privacy applied at serialization, and the 404-not-empty-shell rule as an actual
HTTP response.
"""

import pytest

SONG = {"artist": "Tame Impala", "album": "Currents", "title": "Let It Happen"}


def signup(client, email="kaan@example.com", handle="kaan"):
    r = client.post("/v1/auth/signup", json={"email": email, "password": "a good long one"})
    assert r.status_code == 200, r.get_json()
    if handle:
        r = client.post("/v1/handle/claim", json={"handle": handle})
        assert r.status_code == 200, r.get_json()
    return r.get_json()


def rate(client, value=8.0, **overrides):
    op = {"op": "rate", **SONG, "value": value, "label": str(value), **overrides}
    return client.post("/v1/sync", json={"ops": [op]})


# ------------------------------------------------------------------- basics ----


def test_healthz(client):
    assert client.get("/healthz").get_json()["ok"] is True


def test_signup_login_logout(client):
    signup(client, handle=None)
    assert client.get("/v1/me").status_code == 200

    client.post("/v1/auth/logout")
    assert client.get("/v1/me").status_code == 401

    r = client.post(
        "/v1/auth/login", json={"email": "kaan@example.com", "password": "a good long one"}
    )
    assert r.status_code == 200


def test_signup_sends_a_verification_email(client, app):
    signup(client, handle=None)
    assert any("confirm your address" in subject for _to, subject, _body in app.mailbox.sent)


def test_signup_does_not_reveal_existing_accounts(client, app):
    signup(client, handle=None)
    fresh = app.test_client()

    r = fresh.post(
        "/v1/auth/signup", json={"email": "kaan@example.com", "password": "another long one"}
    )

    # identical shape to a successful signup — no enumeration oracle
    assert r.status_code == 200 and r.get_json()["check_your_email"] is True
    assert fresh.get("/v1/me").status_code == 401  # but they are NOT logged in


def test_weak_passwords_rejected(client):
    r = client.post("/v1/auth/signup", json={"email": "a@b.co", "password": "short"})
    assert r.status_code == 400 and r.get_json()["code"] == "weak_password"


# ------------------------------------------------------------------ handles ----


def test_rating_requires_a_handle(client):
    signup(client, handle=None)
    r = rate(client)
    assert r.status_code == 403 and r.get_json()["code"] == "no_handle"


def test_handle_availability_and_suggestion(client):
    signup(client, handle="kaan")
    other = client.application.test_client()
    signup(other, email="mert@example.com", handle=None)

    r = other.get("/v1/handle/available?handle=kaan")
    body = r.get_json()
    assert body["available"] is False and body["suggestion"] == "kaan2"


def test_reserved_handles_refused(client):
    signup(client, handle=None)
    r = client.post("/v1/handle/claim", json={"handle": "settings"})
    assert r.status_code == 400 and r.get_json()["code"] == "handle_rejected"


# --------------------------------------------------- nothing until rated ----


def test_an_unrated_work_is_a_404_not_an_empty_shell(client):
    r = client.get("/v1/works/doesnotexistkey00")
    assert r.status_code == 404
    assert r.get_json() == {"ok": False, "exists": False, "work_key": "doesnotexistkey00"}


def test_first_rating_creates_the_work_and_says_so(client):
    signup(client)
    result = rate(client).get_json()["results"][0]

    assert result["status"] == "stored"
    assert result["first_press"] is True
    assert result["average"] == 8.0

    r = client.get(f"/v1/works/{result['work_key']}")
    assert r.status_code == 200
    assert r.get_json()["work"]["first_press"]["handle"] == "kaan"


def test_second_rater_is_not_a_first_press(client, app):
    signup(client)
    key = rate(client, 8.0).get_json()["results"][0]["work_key"]

    second = app.test_client()
    signup(second, email="mert@example.com", handle="mert")
    result = rate(second, 6.0).get_json()["results"][0]

    assert result["first_press"] is False
    assert result["count"] == 2
    assert result["average"] == 7.0
    assert client.get(f"/v1/works/{key}").get_json()["work"]["first_press"]["handle"] == "kaan"


def test_unrating_the_last_verdict_removes_the_work_entirely(client):
    signup(client)
    key = rate(client).get_json()["results"][0]["work_key"]

    r = client.post("/v1/sync", json={"ops": [{"op": "unrate", **SONG}]})
    assert r.get_json()["results"][0]["status"] == "deleted"

    assert client.get(f"/v1/works/{key}").status_code == 404


def test_variant_tags_reach_the_same_work_over_http(client, app):
    signup(client)
    key = rate(client, 9.0).get_json()["results"][0]["work_key"]

    second = app.test_client()
    signup(second, email="mert@example.com", handle="mert")
    op = {
        "op": "rate",
        "artist": "Tame Impala",
        "album": "Currents (Deluxe)",
        "title": "Let It Happen - 2015 Remaster",
        "value": 7.0,
        "label": "7",
    }
    result = second.post("/v1/sync", json={"ops": [op]}).get_json()["results"][0]

    assert result["work_key"] == key
    assert result["count"] == 2


# ---------------------------------------------------------------- sync ops ----


def test_a_batch_survives_one_bad_op(client):
    signup(client)
    r = client.post(
        "/v1/sync",
        json={
            "ops": [
                {"op": "rate", **SONG, "value": 8.0, "label": "8"},
                {"op": "rate", "artist": "x", "album": "y", "title": "", "value": 5},
                {"op": "rate", "artist": "Boards of Canada", "album": "Geogaddi",
                 "title": "Dawn Chorus", "value": 9.0, "label": "9"},
            ]
        },
    )
    statuses = [x["status"] for x in r.get_json()["results"]]
    assert statuses == ["stored", "rejected", "stored"]


def test_replaying_the_same_op_is_safe(client):
    signup(client)
    first = rate(client, 8.0, rev=1).get_json()["results"][0]
    again = rate(client, 8.0, rev=1).get_json()["results"][0]

    assert again["count"] == 1 == first["count"]


def test_a_stale_op_is_skipped_not_applied(client):
    signup(client)
    rate(client, 9.0, rev=5)
    result = rate(client, 1.0, rev=2).get_json()["results"][0]

    assert result["status"] == "skipped"
    key = rate(client, 9.0, rev=5).get_json()["results"][0]["work_key"]
    assert client.get(f"/v1/works/{key}").get_json()["work"]["average"] == 9.0


def test_only_a_paired_device_may_claim_a_live_stamp(client):
    """Provenance is a credibility claim, so the web can't just assert it."""
    signup(client)
    key = rate(client, 8.0, provenance="live").get_json()["results"][0]["work_key"]

    verdicts = client.get("/v1/u/kaan/shelf").get_json()["verdicts"]
    assert verdicts[0]["live"] is False
    assert key


def test_out_of_range_values_rejected(client):
    signup(client)
    assert rate(client, 11.0).get_json()["results"][0]["status"] == "rejected"
    assert rate(client, 0).get_json()["results"][0]["status"] == "rejected"


# ------------------------------------------------------------------ pairing ----


def test_full_pairing_flow_gives_the_widget_a_working_token(client, app):
    signup(client)
    nonce = "n" * 32

    start = client.post(
        "/v1/pair/start", json={"device_nonce": nonce, "device_name": "kaan's pc"}
    ).get_json()
    assert "-" in start["code"]

    widget = app.test_client()  # a separate client: no session cookie
    assert widget.post("/v1/pair/poll", json={"device_nonce": nonce}).get_json()["pending"] is True

    page = client.get(start["url"].replace("http://127.0.0.1:5000", ""))
    assert b"link this device?" in page.data
    client.post("/link", data={"code": start["code"].replace("-", "")})

    polled = widget.post("/v1/pair/poll", json={"device_nonce": nonce}).get_json()
    assert polled["pending"] is False

    token = polled["device_token"]
    me = widget.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
    assert me.get_json()["me"]["handle"] == "kaan"


def test_a_paired_widget_may_stamp_live(client, app):
    signup(client)
    nonce = "n" * 32
    start = client.post("/v1/pair/start", json={"device_nonce": nonce}).get_json()
    client.post("/link", data={"code": start["code"].replace("-", "")})
    widget = app.test_client()
    token = widget.post("/v1/pair/poll", json={"device_nonce": nonce}).get_json()["device_token"]

    widget.post(
        "/v1/sync",
        json={"ops": [{"op": "rate", **SONG, "value": 8.0, "label": "8", "provenance": "live"}]},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert client.get("/v1/u/kaan/shelf").get_json()["verdicts"][0]["live"] is True


def test_a_bad_device_token_is_simply_not_signed_in(client):
    r = client.get("/v1/me", headers={"Authorization": "Bearer nope"})
    assert r.status_code == 401


# ------------------------------------------------------------------ privacy ----


def test_a_private_note_is_hidden_from_everyone_else(client, app):
    signup(client)
    rate(client, 8.0, note="this is just for me", note_public=False)

    mine = client.get("/v1/u/kaan/shelf").get_json()["verdicts"][0]
    assert mine["note"] == "this is just for me"

    stranger = app.test_client()
    theirs = stranger.get("/v1/u/kaan/shelf").get_json()["verdicts"][0]
    assert theirs["note"] is None
    assert theirs["note_hidden"] is True


def test_a_private_profile_is_not_readable(client, app):
    signup(client)
    rate(client)
    client.patch("/v1/me", json={"is_private": True})

    stranger = app.test_client()
    assert stranger.get("/v1/u/kaan").get_json()["profile"]["visible"] is False
    assert stranger.get("/v1/u/kaan/shelf").status_code == 403
    # ...but the owner still sees their own
    assert client.get("/v1/u/kaan/shelf").status_code == 200


def test_a_non_public_rating_stays_off_the_public_shelf(client, app):
    signup(client)
    rate(client, 8.0, is_public=False)

    assert client.get("/v1/u/kaan/shelf").get_json()["verdicts"] != []
    stranger = app.test_client()
    assert stranger.get("/v1/u/kaan/shelf").get_json()["verdicts"] == []


# ------------------------------------------------------------------- social ----


def test_follow_and_feed(client, app):
    signup(client)
    rate(client, 8.0, note="a banger")

    follower = app.test_client()
    signup(follower, email="mert@example.com", handle="mert")

    assert follower.post("/v1/follow/kaan").status_code == 200
    feed = follower.get("/v1/feed").get_json()["verdicts"]
    assert len(feed) == 1
    assert feed[0]["by"]["handle"] == "kaan"
    assert feed[0]["work"]["title"] == "Let It Happen"


def test_cosign_counts(client, app):
    signup(client)
    rate(client)
    rating_id = client.get("/v1/u/kaan/shelf").get_json()["verdicts"][0]["id"]

    other = app.test_client()
    signup(other, email="mert@example.com", handle="mert")

    assert other.post(f"/v1/cosign/{rating_id}").get_json()["count"] == 1
    assert other.post(f"/v1/cosign/{rating_id}").get_json()["count"] == 1  # idempotent
    assert other.delete(f"/v1/cosign/{rating_id}").get_json()["count"] == 0


def test_you_cannot_cosign_yourself(client):
    signup(client)
    rate(client)
    rating_id = client.get("/v1/u/kaan/shelf").get_json()["verdicts"][0]["id"]
    assert client.post(f"/v1/cosign/{rating_id}").status_code == 400


def test_blocking_hides_people_from_each_other(client, app):
    signup(client)
    other = app.test_client()
    signup(other, email="mert@example.com", handle="mert")
    other.post("/v1/follow/kaan")

    client.post("/v1/block/mert")

    # the follow is severed, and they can't re-follow
    assert other.get("/v1/feed").get_json()["verdicts"] == []
    assert other.post("/v1/follow/kaan").status_code == 404


def test_reports_need_a_reason_and_a_target(client):
    signup(client)
    assert client.post("/v1/report", json={"handle": "kaan"}).status_code == 400
    assert client.post("/v1/report", json={"reason": "spam"}).status_code == 400


# ------------------------------------------------------------------ albums ----


def test_album_page_aggregates_and_histograms(client, app):
    signup(client)
    rate(client, 9.0)
    client.post(
        "/v1/sync",
        json={"ops": [{"op": "rate", "artist": "Tame Impala", "album": "Currents",
                       "title": "Eventually", "value": 7.0, "label": "7"}]},
    )
    album_key = client.get("/v1/u/kaan/shelf").get_json()["verdicts"][0]["work"]["album_key"]

    body = client.get(f"/v1/albums/{album_key}").get_json()["album"]
    assert body["album"] == "Currents"
    assert body["rated_tracks"] == 2
    assert body["average"] == 8.0
    assert sum(col["count"] for col in body["histogram"]) == 2


def test_an_album_nobody_rated_is_a_404(client):
    assert client.get("/v1/albums/nothinghere00000000").status_code == 404


# -------------------------------------------------------------------- rest ----


def test_export_returns_everything(client):
    signup(client)
    rate(client, 8.0, note="mine")
    body = client.get("/v1/export").get_json()
    assert body["handle"] == "kaan"
    assert body["ratings"][0]["note"] == "mine"


def test_account_deletion_takes_orphaned_works_with_it(client):
    signup(client)
    key = rate(client).get_json()["results"][0]["work_key"]

    assert client.delete("/v1/account", json={"confirm": "wrong"}).status_code == 400
    assert client.delete("/v1/account", json={"confirm": "kaan"}).status_code == 200

    assert client.get(f"/v1/works/{key}").status_code == 404
    assert client.get("/v1/me").status_code == 401


def test_rate_limiting_eventually_says_no(client):
    for _ in range(5):
        client.post("/v1/auth/signup", json={"email": "x@y.co", "password": "a good long one"})
    r = client.post("/v1/auth/signup", json={"email": "z@y.co", "password": "a good long one"})
    assert r.status_code == 429
