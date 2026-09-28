from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from conftest import SECRET, CaptureMailer, auth, grant_access
from orl_web.app import create_app
from orl_web.config import Settings
from orl_web.models import AccessRequest, AuditEvent, BrowserSession, Role, User


ADMIN = auth("admin-1", "admin")
REQUEST = {"email": "Ada@Example.edu", "name": "Ada Lovelace", "role": "researcher",
           "discipline": "Analytical engines", "note": "How far can mechanical computation go?"}


def request_link(client, email):
    return client.post("/v1/auth/magic-link", json={"email": email})


def verify(client, url):
    token = parse_qs(urlsplit(url).query)["token"][0]
    return client.get(f"/auth/verify?token={token}", follow_redirects=False)


def request_id(client, email):
    listed = client.get("/v1/admin/access-requests?status=all", headers=ADMIN).json()["requests"]
    return next(item["request_id"] for item in listed if item["email"] == email)


def decide(client, email, action, reason="Recorded decision."):
    return client.post(f"/v1/admin/access-requests/{request_id(client, email)}/decision",
                       json={"action": action, "reason": reason}, headers=ADMIN)


@pytest.mark.spec("WEB-ACCESS-001")
def test_invite_mode_sends_links_only_to_approved_or_elevated_addresses(
        client, mailer, session_factory):
    neutral = request_link(client, "stranger@example.org")
    assert neutral.status_code == 202 and mailer.deliveries == []
    assert client.post("/v1/access-requests", json={**REQUEST, "email": "stranger@example.org"}).status_code == 202
    assert request_link(client, "stranger@example.org").json() == neutral.json()
    assert mailer.deliveries == []

    grant_access(client, "stranger@example.org")
    assert request_link(client, "stranger@example.org").json() == neutral.json()
    assert [email for email, _ in mailer.deliveries] == ["stranger@example.org"]
    assert verify(client, mailer.deliveries[-1][1]).status_code == 303

    with session_factory() as session:
        session.add(User(external_subject="email:mod@example.org", email="mod@example.org",
                         role=Role.moderator))
        session.commit()
    request_link(client, "mod@example.org")
    assert mailer.deliveries[-1][0] == "mod@example.org"


@pytest.mark.spec("WEB-ACCESS-001")
def test_revocation_blocks_pending_links_and_every_mode(session_factory):
    mailer = CaptureMailer()
    settings = Settings(jwt_secret=SECRET, access_mode="open", admin_emails=("owner@example.org",))
    with TestClient(create_app(settings=settings, session_factory=session_factory,
                               mailer=mailer)) as client:
        request_link(client, "anyone@example.org")
        assert mailer.deliveries[-1][0] == "anyone@example.org"
        grant_access(client, "anyone@example.org")
        request_link(client, "anyone@example.org")
        pending_url = mailer.deliveries[-1][1]
        assert decide(client, "anyone@example.org", "revoke", "Left the cohort.").status_code == 200
        rejected = verify(client, pending_url)
        assert rejected.status_code == 400 and "invalid or has expired" in rejected.text
        sent = len(mailer.deliveries)
        request_link(client, "anyone@example.org")
        assert len(mailer.deliveries) == sent

        client.post("/v1/access-requests", json={**REQUEST, "email": "owner@example.org"})
        grant_access(client, "owner@example.org")
        decide(client, "owner@example.org", "revoke")
        request_link(client, "owner@example.org")
        assert mailer.deliveries[-1][0] == "owner@example.org"
        assert client.get("/join").text.count("Sign in with email") == 1


@pytest.mark.spec("WEB-ACCESS-002")
def test_invitation_requests_are_neutral_bounded_and_never_overwritten(client, session_factory):
    page = client.get("/join")
    assert page.status_code == 200 and 'id="join-form"' in page.text
    assert "open to read without an account" in page.text
    first = client.post("/v1/access-requests", json=REQUEST)
    assert first.status_code == 202
    replay = client.post("/v1/access-requests", json={**REQUEST, "name": "Impostor", "note": "Changed"})
    assert replay.json() == first.json()
    grant_access(client, "ada@example.edu")
    assert client.post("/v1/access-requests", json=REQUEST).json() == first.json()
    with session_factory() as session:
        stored = session.scalar(select(AccessRequest))
        assert stored.email == "ada@example.edu" and stored.name == "Ada Lovelace"
        assert stored.note == REQUEST["note"] and stored.status.value == "approved"
    for invalid in ({**REQUEST, "email": "not-an-email"}, {**REQUEST, "name": "   "},
                    {**REQUEST, "role": "influencer"}, {**REQUEST, "note": "x" * 1001},
                    {**REQUEST, "website": "https://spam.example"}):
        assert client.post("/v1/access-requests", json=invalid).status_code == 422


@pytest.mark.spec("WEB-ACCESS-002")
def test_invitation_request_cap_is_global_and_reveals_nothing(session_factory):
    settings = Settings(jwt_secret=SECRET, access_request_limit_per_hour=2)
    with TestClient(create_app(settings=settings, session_factory=session_factory,
                               mailer=CaptureMailer())) as client:
        for number in range(2):
            assert client.post("/v1/access-requests", json={
                **REQUEST, "email": f"person{number}@example.org"}).status_code == 202
        throttled_new = client.post("/v1/access-requests", json={**REQUEST, "email": "new@example.org"})
        throttled_known = client.post("/v1/access-requests", json={**REQUEST, "email": "person0@example.org"})
        assert throttled_new.status_code == throttled_known.status_code == 429
        assert throttled_new.json() == throttled_known.json()
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(AccessRequest)) == 2


@pytest.mark.spec("WEB-ACCESS-003", "WEB-SEC-002")
def test_admins_decide_requests_with_audited_transitions(client, mailer, session_factory):
    client.post("/v1/access-requests", json=REQUEST)
    listed = client.get("/v1/admin/access-requests", headers=ADMIN).json()
    assert listed["access_mode"] == "invite" and listed["requests"][0]["name"] == "Ada Lovelace"
    assert client.get("/v1/admin/access-requests", headers=auth("mod-1", "moderator")).status_code == 403
    assert client.post(f"/v1/admin/access-requests/{listed['requests'][0]['request_id']}/decision",
                       json={"action": "approve", "reason": "Known researcher."},
                       headers=auth("mod-1", "moderator")).status_code == 403
    assert client.post("/v1/admin/access-requests/missing/decision",
                       json={"action": "approve", "reason": "Known researcher."},
                       headers=ADMIN).status_code == 404

    assert decide(client, "ada@example.edu", "revoke").status_code == 409
    declined = decide(client, "ada@example.edu", "decline", "Cohort is full this month.")
    assert declined.json()["status"] == "declined" and declined.json()["notified"] is False
    assert decide(client, "ada@example.edu", "decline").json()["idempotent_replay"] is True
    approved = decide(client, "ada@example.edu", "approve", "A place opened.")
    assert approved.json()["status"] == "approved" and approved.json()["notified"] is True
    assert mailer.approvals == [("ada@example.edu", "http://127.0.0.1:8080/login")]
    assert decide(client, "ada@example.edu", "decline").status_code == 409
    assert client.get("/v1/admin/access-requests?status=approved", headers=ADMIN).json()["requests"][0][
        "decision_reason"] == "A place opened."

    request_link(client, "ada@example.edu")
    assert verify(client, mailer.deliveries[-1][1]).status_code == 303
    assert client.get("/v1/auth/session").json()["authenticated"] is True
    revoked = decide(client, "ada@example.edu", "revoke", "Shared their account.")
    assert revoked.json()["status"] == "revoked"
    assert client.get("/v1/auth/session").json() == {"authenticated": False}
    assert decide(client, "ada@example.edu", "approve", "Access restored.").json()["status"] == "approved"
    with session_factory() as session:
        assert session.scalar(select(BrowserSession)).revoked_at is not None
        actions = [event.action for event in session.scalars(select(AuditEvent).where(
            AuditEvent.target_type == "access_request").order_by(AuditEvent.created_at))]
        assert actions == ["access.declined", "access.approved", "access.revoked", "access.approved"]
        assert all("ada@example.edu" not in str(event.details) for event in session.scalars(
            select(AuditEvent).where(AuditEvent.target_type == "access_request")))


@pytest.mark.spec("WEB-ACCESS-003")
def test_direct_invitations_and_failed_notices_keep_the_decision(session_factory):
    class FailingMailer(CaptureMailer):
        def send_access_approved(self, email, sign_in_url):
            raise OSError("smtp unavailable")

    settings = Settings(jwt_secret=SECRET)
    with TestClient(create_app(settings=settings, session_factory=session_factory,
                               mailer=FailingMailer())) as client:
        invited = client.post("/v1/admin/access", json={
            "email": "Friend@Example.org", "name": "A Friend", "reason": "Founding cohort."},
            headers=ADMIN)
        assert invited.status_code == 200
        assert invited.json()["status"] == "approved" and invited.json()["notified"] is False
        assert invited.json()["source"] == "invite" and invited.json()["email"] == "friend@example.org"
        again = client.post("/v1/admin/access", json={"email": "friend@example.org", "reason": "Again."},
                            headers=ADMIN)
        assert again.json()["idempotent_replay"] is True
        client.post("/v1/access-requests", json=REQUEST)
        promoted = client.post("/v1/admin/access", json={"email": "ada@example.edu", "reason": "Invited."},
                               headers=ADMIN).json()
        assert promoted["status"] == "approved" and promoted["source"] == "request"
        assert promoted["name"] == "Ada Lovelace"
        assert client.post("/v1/admin/access", json={"email": "x@example.org", "reason": "Invited."},
                           headers=auth("editor-1", "editor")).status_code == 403
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(AccessRequest).where(
            AccessRequest.status == "approved")) == 2
