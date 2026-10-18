from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from conftest import SECRET, CaptureMailer, auth, grant_access, publication_bundle
from orl_web.app import create_app
from orl_web.config import Settings
from orl_web.contracts import content_sha256
from orl_web.models import (AccessRequest, AccessStatus, Article, AuditEvent, EmailDelivery,
                            QuestionCluster, ResearchSubscription, Role, User)


EDITOR = auth("editor-1", "editor")
ADMIN = auth("admin-1", "admin")


def publish(client, session_factory, *, bundle_id, slug, domain, title=None):
    with session_factory() as session:
        cluster = QuestionCluster(canonical_question=f"What does the evidence show in {domain}?",
                                  tags=[], domain=domain)
        session.add(cluster)
        session.commit()
        cluster_id = cluster.id
    payload = publication_bundle(bundle_id=bundle_id, slug=slug)
    payload["cluster_id"] = cluster_id
    payload["article"]["title"] = title or f"Evidence in {domain.title()}"
    payload["article"]["summary"] = f"What the {domain} literature supports."
    payload["content_sha256"] = content_sha256(payload)
    assert client.post("/v1/admin/publications", json=payload,
                       headers=auth("core", "service")).status_code == 201
    assert client.post(f"/v1/admin/publications/{bundle_id}/publish", headers=EDITOR).status_code == 200
    return payload


def run(client, limit=None, headers=EDITOR):
    body = {} if limit is None else {"limit": limit}
    return client.post("/v1/admin/deliveries/run", json=body, headers=headers)


def unsubscribe_path(mailer, email):
    return urlsplit(next(url for to, _, url in mailer.approvals if to == email)).path


def member(session, email):
    return session.scalar(select(User).where(User.email == email))


def interests(session, email):
    user = member(session, email)
    return sorted((item.kind, item.value_key) for item in session.scalars(
        select(ResearchSubscription).where(ResearchSubscription.user_id == user.id)))


@pytest.mark.spec("WEB-MAIL-001")
def test_approval_invitation_and_open_sign_in_create_subscribers(session_factory):
    mailer = CaptureMailer()
    settings = Settings(jwt_secret=SECRET, admin_emails=("owner@example.org",))
    with TestClient(create_app(settings=settings, session_factory=session_factory,
                               mailer=mailer)) as client:
        client.post("/v1/access-requests", json={"email": "reader@example.org", "name": "Reader"})
        with session_factory() as session:
            assert member(session, "reader@example.org") is None
        request_id = client.get("/v1/admin/access-requests", headers=ADMIN).json()["requests"][0][
            "request_id"]
        decided = client.post(f"/v1/admin/access-requests/{request_id}/decision",
                              json={"action": "approve", "reason": "First cohort."}, headers=ADMIN)
        assert decided.json()["notified"] is True
        grant_access(client, "owner@example.org")
        email, sign_in_url, unsubscribe_url = mailer.approvals[0]
        assert (email, sign_in_url) == ("reader@example.org", "http://127.0.0.1:8080/login")
        assert client.get(urlsplit(unsubscribe_url).path).status_code == 200
        with session_factory() as session:
            reader = member(session, "reader@example.org")
            assert reader.role == Role.user and reader.email_opt_out_at is None
            assert reader.email_subscribed_at is not None
            assert interests(session, "reader@example.org") == [("all", "all")]
            assert member(session, "owner@example.org").role == Role.admin
            session.query(ResearchSubscription).filter(
                ResearchSubscription.user_id == reader.id).delete()
            session.add(ResearchSubscription(user_id=reader.id, kind="domain", value_key="physics",
                                             label="Physics"))
            session.commit()

        client.post(f"/v1/admin/access-requests/{request_id}/decision",
                    json={"action": "revoke", "reason": "Paused."}, headers=ADMIN)
        client.post(f"/v1/admin/access-requests/{request_id}/decision",
                    json={"action": "approve", "reason": "Restored."}, headers=ADMIN)
        with session_factory() as session:
            assert session.query(User).filter(User.email == "reader@example.org").count() == 1
            assert interests(session, "reader@example.org") == [("domain", "physics")]

        with session_factory() as session:
            session.add(AccessRequest(email="legacy@example.org", name="Legacy", source="existing",
                                      status=AccessStatus.approved))
            session.commit()
        assert run(client).status_code == 200
        with session_factory() as session:
            assert interests(session, "legacy@example.org") == [("all", "all")]

    open_mailer = CaptureMailer()
    open_settings = Settings(jwt_secret=SECRET, access_mode="open")
    with TestClient(create_app(settings=open_settings, session_factory=session_factory,
                               mailer=open_mailer)) as client:
        client.post("/v1/auth/magic-link", json={"email": "walk-in@example.org"})
        token = parse_qs(urlsplit(open_mailer.deliveries[-1][1]).query)["token"][0]
        assert client.get(f"/auth/verify?token={token}", follow_redirects=False).status_code == 303
        with session_factory() as session:
            assert interests(session, "walk-in@example.org") == [("all", "all")]
        join = client.get("/join").text
        assert "Subscribe to TruthLM" in join and "paid" not in join.lower()


@pytest.mark.spec("WEB-MAIL-002")
def test_delivery_sends_each_subscriber_one_email_of_new_matching_research(
        client, mailer, session_factory):
    publish(client, session_factory, bundle_id="bundle-old", slug="old-research", domain="economics",
            title="Published before anyone subscribed")
    for email in ("all@example.org", "bio@example.org", "quiet@example.org", "gone@example.org"):
        grant_access(client, email)
    with session_factory() as session:
        bio = member(session, "bio@example.org")
        session.query(ResearchSubscription).filter(ResearchSubscription.user_id == bio.id).delete()
        session.add(ResearchSubscription(user_id=bio.id, kind="domain", value_key="biology",
                                         label="Biology"))
        session.commit()
    assert client.post(unsubscribe_path(mailer, "quiet@example.org")).status_code == 200
    gone = next(item for item in client.get("/v1/admin/access-requests?status=approved",
                                             headers=ADMIN).json()["requests"]
                if item["email"] == "gone@example.org")
    client.post(f"/v1/admin/access-requests/{gone['request_id']}/decision",
                json={"action": "revoke", "reason": "Left."}, headers=ADMIN)

    publish(client, session_factory, bundle_id="bundle-econ", slug="econ-research",
            domain="economics", title="Fees & returns <em>after costs</em>")
    publish(client, session_factory, bundle_id="bundle-bio", slug="bio-research", domain="biology")
    assert run(client).json() == {"queued": 3, "emails_sent": 2, "emails_failed": 0, "skipped": 0,
                                  "remaining": 0}
    sent = {email: message for email, message in mailer.research}
    assert set(sent) == {"all@example.org", "bio@example.org"}
    everything, biology = sent["all@example.org"], sent["bio@example.org"]
    assert everything.subject == "2 new TruthLM investigations"
    assert biology.subject == "New on TruthLM: Evidence in Biology"
    assert "Fees & returns <em>after costs</em>" in everything.text
    assert "Fees &amp; returns &lt;em&gt;after costs&lt;/em&gt;" in everything.html
    assert "<em>after costs</em>" not in everything.html
    assert "http://127.0.0.1:8080/research/econ-research" in everything.text
    assert "Economics" in everything.text and "Biology" in everything.text
    assert "Fees & returns" not in biology.text
    for message in sent.values():
        assert "Published before anyone subscribed" not in message.text
        assert "researched by AI agents and reviewed by a person" in message.text
        assert "http://127.0.0.1:8080/subscriptions" in message.text
        assert message.unsubscribe_url in message.text and message.unsubscribe_url in message.html
    assert sent["all@example.org"].unsubscribe_url != sent["bio@example.org"].unsubscribe_url

    assert run(client).json() == {"queued": 0, "emails_sent": 0, "emails_failed": 0, "skipped": 0,
                                  "remaining": 0}
    correction = publication_bundle(bundle_id="bundle-econ-2", slug="econ-research", revision=2,
                                    supersedes_bundle_id="bundle-econ",
                                    correction_summary="Corrected the cost assumption.")
    assert client.post("/v1/admin/publications", json=correction,
                       headers=auth("core", "service")).status_code == 201
    assert client.post("/v1/admin/publications/bundle-econ-2/publish",
                       headers=EDITOR).status_code == 200
    assert run(client).json()["queued"] == 0 and len(mailer.research) == 2

    publish(client, session_factory, bundle_id="bundle-bio-2", slug="bio-research-2", domain="biology")
    assert run(client, limit=1).json() == {"queued": 2, "emails_sent": 1, "emails_failed": 0,
                                           "skipped": 0, "remaining": 1}
    assert client.post("/v1/admin/publications/bundle-bio-2/retract", json={"reason": "Flawed data."},
                       headers=EDITOR).status_code == 200
    assert run(client).json() == {"queued": 0, "emails_sent": 0, "emails_failed": 0, "skipped": 1,
                                  "remaining": 0}
    publish(client, session_factory, bundle_id="bundle-bio-3", slug="bio-research-3", domain="biology")
    queued = run(client, limit=1).json()
    assert queued["queued"] == 2 and queued["remaining"] == 1
    assert mailer.research[-1][0] == "all@example.org"
    assert client.post(unsubscribe_path(mailer, "bio@example.org")).status_code == 200
    assert run(client).json() == {"queued": 0, "emails_sent": 0, "emails_failed": 0, "skipped": 1,
                                  "remaining": 0}
    assert {to for to, _ in mailer.research} == {"all@example.org", "bio@example.org"}


@pytest.mark.spec("WEB-MAIL-003", "WEB-SEC-002")
def test_delivery_runs_are_bounded_resumable_and_retry_failures_three_times(session_factory):
    class FlakyMailer(CaptureMailer):
        def __init__(self):
            super().__init__()
            self.failing = set()

        def send_research(self, email, message):
            if email in self.failing:
                raise OSError("mailbox unavailable")
            super().send_research(email, message)

    mailer = FlakyMailer()
    settings = Settings(jwt_secret=SECRET, delivery_batch_size=1)
    with TestClient(create_app(settings=settings, session_factory=session_factory,
                               mailer=mailer)) as client:
        for email in ("a@example.org", "b@example.org", "c@example.org"):
            grant_access(client, email)
        publish(client, session_factory, bundle_id="bundle-1", slug="first", domain="statistics")
        mailer.failing = {"b@example.org"}

        for headers in (auth("member", "user"), auth("mod", "moderator")):
            assert run(client, headers=headers).status_code == 403
            assert client.get("/v1/admin/deliveries", headers=headers).status_code == 403
        for limit in (0, 1001):
            assert run(client, limit=limit).status_code == 422

        assert run(client).json() == {"queued": 3, "emails_sent": 1, "emails_failed": 0,
                                      "skipped": 0, "remaining": 2}
        assert run(client, headers=auth("core", "service")).json()["emails_failed"] == 1
        assert run(client, headers=ADMIN).json() == {"queued": 0, "emails_sent": 1,
                                                     "emails_failed": 0, "skipped": 0, "remaining": 1}
        assert [run(client).json()["emails_failed"] for _ in range(2)] == [1, 1]
        mailer.failing = set()
        assert run(client).json() == {"queued": 0, "emails_sent": 0, "emails_failed": 0,
                                      "skipped": 0, "remaining": 0}
        assert [to for to, _ in mailer.research] == ["a@example.org", "c@example.org"]
        with session_factory() as session:
            failed = session.scalar(select(EmailDelivery).where(EmailDelivery.status == "failed"))
            assert failed.attempts == 3 and "mailbox unavailable" in failed.last_error

        publish(client, session_factory, bundle_id="bundle-2", slug="second", domain="statistics")
        with session_factory() as session:
            article = session.scalar(select(Article).where(Article.slug == "second"))
            interrupted = member(session, "a@example.org")
            session.add(EmailDelivery(user_id=interrupted.id, article_id=article.id,
                                      status="sending", attempts=1))
            session.commit()
        assert run(client, limit=5).json() == {"queued": 2, "emails_sent": 2, "emails_failed": 0,
                                               "skipped": 0, "remaining": 0}
        assert [to for to, _ in mailer.research[-2:]] == ["b@example.org", "c@example.org"]
        status = client.get("/v1/admin/deliveries", headers=EDITOR).json()
        assert status["subscribers"] == 3 and status["remaining"] == 0
        assert status["deliveries"] == {"pending": 0, "sending": 1, "sent": 4, "failed": 1,
                                        "skipped": 0}
        assert status["last_sent_at"].endswith("Z")

        page = client.get("/editor").text
        assert "Editorial access required" in page and 'id="delivery-panel"' not in page
        with session_factory() as session:
            session.add(User(external_subject="email:ed@example.org", email="ed@example.org",
                             role=Role.editor))
            session.commit()
        client.post("/v1/auth/magic-link", json={"email": "ed@example.org"})
        token = parse_qs(urlsplit(mailer.deliveries[-1][1]).query)["token"][0]
        client.get(f"/auth/verify?token={token}")
        page = client.get("/editor").text
        assert 'id="delivery-panel"' in page and "Email new research" in page
        with session_factory() as session:
            actions = [event.action for event in session.scalars(select(AuditEvent).where(
                AuditEvent.action == "delivery.run"))]
            assert len(actions) >= 7


@pytest.mark.spec("WEB-MAIL-004")
def test_signed_unsubscribe_stops_delivery_and_members_can_resubscribe(client, mailer, session_factory):
    grant_access(client, "reader@example.org")
    path = unsubscribe_path(mailer, "reader@example.org")
    page = client.get(path)
    assert page.status_code == 200 and 'method="post"' in page.text
    assert "Unsubscribe from TruthLM research emails" in page.text
    assert "reader@example.org" not in page.text
    tampered = path[:-1] + ("0" if path[-1] != "0" else "1")
    user_id = path.split("/")[2]
    for invalid in (tampered, path.replace(user_id, "not-a-user"), f"/unsubscribe/{user_id}/short"):
        assert client.get(invalid).status_code == 404
        assert client.post(invalid).status_code == 404
    one_click = client.post(path, content="List-Unsubscribe=One-Click",
                            headers={"Content-Type": "application/x-www-form-urlencoded"})
    assert one_click.status_code == 200 and "You are unsubscribed" in one_click.text
    assert "reader@example.org" not in one_click.text
    assert client.post(path).status_code == 200
    assert "You are unsubscribed" in client.get(path).text
    with session_factory() as session:
        reader = member(session, "reader@example.org")
        assert reader.email_opt_out_at is not None
        assert session.query(AuditEvent).filter(AuditEvent.action == "email.unsubscribed").count() == 1

    publish(client, session_factory, bundle_id="bundle-away", slug="while-away", domain="physics",
            title="Published while unsubscribed")
    assert run(client).json()["queued"] == 0 and mailer.research == []

    client.post("/v1/auth/magic-link", json={"email": "reader@example.org"})
    token = parse_qs(urlsplit(mailer.deliveries[-1][1]).query)["token"][0]
    client.get(f"/auth/verify?token={token}")
    csrf = client.get("/v1/auth/session").json()["csrf_token"]
    page = client.get("/subscriptions").text
    assert "Email delivery" in page and 'id="email-toggle"' in page
    assert client.get("/v1/subscriptions").json()["email_enabled"] is False
    assert client.put("/v1/subscriptions/email", json={"enabled": True}).status_code == 403
    enabled = client.put("/v1/subscriptions/email", json={"enabled": True}, headers={"X-CSRF-Token": csrf})
    assert enabled.json() == {"email_enabled": True}
    assert client.get("/v1/subscriptions").json()["email_enabled"] is True

    publish(client, session_factory, bundle_id="bundle-back", slug="after-return", domain="physics",
            title="Published after returning")
    assert run(client).json()["emails_sent"] == 1
    assert "Published after returning" in mailer.research[-1][1].text
    assert "Published while unsubscribed" not in mailer.research[-1][1].text

    disabled = client.put("/v1/subscriptions/email", json={"enabled": False}, headers={"X-CSRF-Token": csrf})
    assert disabled.json() == {"email_enabled": False}
    assert client.put("/v1/subscriptions/email", json={"enabled": "maybe"},
                      headers={"X-CSRF-Token": csrf}).status_code == 422
    with session_factory() as session:
        actions = [event.action for event in session.scalars(select(AuditEvent).where(
            AuditEvent.target_type == "email_subscription").order_by(AuditEvent.created_at))]
        assert actions == ["email.unsubscribed", "email.subscribed", "email.unsubscribed"]
