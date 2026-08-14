"""Moderation and the kill switch.

These exist because a social app without them becomes someone else's problem
within a week of anyone finding it.
"""

import pytest

from tests.test_api import rate, signup


@pytest.fixture
def moderator(client, app, monkeypatch):
    """@kaan is an admin; @mert is an ordinary user who has said something."""
    monkeypatch.setenv("ADMIN_HANDLES", "kaan")
    signup(client, handle="kaan")

    other = app.test_client()
    signup(other, email="mert@example.com", handle="mert")
    rate(other, 1.0, note="something worth reporting")
    return other


def open_report(client, app):
    rating_id = client.get("/v1/u/mert/shelf").get_json()["verdicts"][0]["id"]
    client.post("/v1/report", json={"rating_id": rating_id, "reason": "abuse"})
    return rating_id


# ------------------------------------------------------------------ access ----


def test_the_admin_page_is_invisible_to_everyone_else(client, moderator, monkeypatch):
    monkeypatch.setenv("ADMIN_HANDLES", "somebody_else")
    # 404 rather than 403: an admin page nobody can use shouldn't announce itself
    assert client.get("/admin").status_code == 404


def test_signed_out_visitors_get_the_same_nothing(app, monkeypatch):
    monkeypatch.setenv("ADMIN_HANDLES", "kaan")
    assert app.test_client().get("/admin").status_code == 404


def test_an_admin_sees_the_queue(client, moderator):
    open_report(client, None)
    body = client.get("/admin").data.decode()
    assert "moderation queue" in body
    assert "abuse" in body
    assert "something worth reporting" in body


# ----------------------------------------------------------------- actions ----


def test_hiding_a_verdict_removes_it_from_public_view(client, moderator, app):
    open_report(client, app)
    report_id = client.get("/admin").data.decode().split('name="report_id" value="')[1].split('"')[0]

    client.post("/admin/act", data={"report_id": report_id, "action": "hide"})

    stranger = app.test_client()
    assert stranger.get("/v1/u/mert/shelf").get_json()["verdicts"] == []
    # hidden, not destroyed — it's still theirs
    assert moderator.get("/v1/u/mert/shelf").get_json()["verdicts"] != []


def test_banning_stops_them_signing_in_and_hides_their_shelf(client, moderator, app):
    open_report(client, app)
    report_id = client.get("/admin").data.decode().split('name="report_id" value="')[1].split('"')[0]

    client.post("/admin/act", data={"report_id": report_id, "action": "ban"})

    assert moderator.get("/v1/me").status_code == 401
    assert app.test_client().get("/@mert").status_code == 404


def test_an_admin_cannot_be_banned_through_the_queue(client, moderator, app):
    """Otherwise one compromised report is a self-inflicted lockout."""
    rating_id = client.get("/v1/u/kaan/shelf")
    rate(client, 5.0)
    rating_id = client.get("/v1/u/kaan/shelf").get_json()["verdicts"][0]["id"]
    moderator.post("/v1/report", json={"rating_id": rating_id, "reason": "retaliation"})
    report_id = client.get("/admin").data.decode().split('name="report_id" value="')[1].split('"')[0]

    client.post("/admin/act", data={"report_id": report_id, "action": "ban"})

    assert client.get("/v1/me").status_code == 200


def test_resolved_reports_leave_the_queue(client, moderator, app):
    open_report(client, app)
    report_id = client.get("/admin").data.decode().split('name="report_id" value="')[1].split('"')[0]

    client.post("/admin/act", data={"report_id": report_id, "action": "dismiss"})

    assert "abuse" not in client.get("/admin").data.decode()


# -------------------------------------------------------------- kill switch ----


def test_read_only_stops_writes_but_not_reads(client, monkeypatch):
    signup(client)
    rate(client, 8.0)

    monkeypatch.setenv("NOSKIPS_READ_ONLY", "1")

    assert client.get("/@kaan").status_code == 200
    assert client.get("/v1/me").status_code == 200

    blocked = rate(client, 2.0)
    assert blocked.status_code == 503
    assert blocked.get_json()["code"] == "read_only"


def test_the_switch_is_off_unless_it_is_really_on(client, monkeypatch):
    signup(client)
    for value in ("", "0", "false"):
        monkeypatch.setenv("NOSKIPS_READ_ONLY", value)
        assert rate(client, 7.0).status_code == 200
