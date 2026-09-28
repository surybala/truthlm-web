from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import func, select

from orl_web.models import AuditEvent, BrowserSession, MagicLinkToken, QuestionReport, User

from conftest import approve, auth, create_cycle, grant_access, submit


def sign_in(client, mailer, email="reader@example.org"):
    assert grant_access(client, email).status_code == 200
    response = client.post("/v1/auth/magic-link", json={"email": email})
    assert response.status_code == 202
    delivered_email, url = mailer.deliveries[-1]
    assert delivered_email == email
    token = parse_qs(urlsplit(url).query)["token"][0]
    verified = client.get(f"/auth/verify?token={token}", follow_redirects=False)
    assert verified.status_code == 303
    assert "HttpOnly" in verified.headers["set-cookie"] and "SameSite=lax" in verified.headers["set-cookie"]
    identity = client.get("/v1/auth/session").json()
    assert identity["authenticated"] is True
    return token, identity["csrf_token"]


@pytest.mark.spec("WEB-AUTH-001", "WEB-AUTH-002")
def test_magic_link_is_hashed_single_use_and_creates_revocable_csrf_session(
        client, mailer, session_factory):
    token, csrf = sign_in(client, mailer)
    cookie = client.cookies.get("truthlm_session")
    assert cookie and token not in cookie and csrf
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(MagicLinkToken)) == 1
        stored = session.scalar(select(MagicLinkToken))
        assert stored.token_hash != token and stored.consumed_at is not None
        browser = session.scalar(select(BrowserSession))
        assert browser.token_hash != cookie and browser.revoked_at is None
        user = session.scalar(select(User).where(User.email.is_not(None)))
        assert user.email == "reader@example.org" and user.role.value == "user"

    assert client.get(f"/auth/verify?token={token}", follow_redirects=False).status_code == 400
    question = {"text": "Does this intervention improve outcomes in independent adult samples?"}
    assert client.post("/v1/questions", json=question,
                       headers={"Idempotency-Key": "browser-question-1"}).status_code == 403
    assert client.post("/v1/questions", json=question, headers={
        "Idempotency-Key": "browser-question-1", "X-CSRF-Token": csrf}).status_code == 201
    response = client.post("/v1/auth/logout", headers={"X-CSRF-Token": csrf})
    assert response.status_code == 204
    assert client.get("/v1/auth/session").json() == {"authenticated": False}
    with session_factory() as session:
        assert session.scalar(select(BrowserSession)).revoked_at is not None


@pytest.mark.spec("WEB-AUTH-001")
def test_magic_link_rate_limit_has_neutral_response(client, mailer, settings):
    grant_access(client, "same@example.org")
    for _ in range(settings.magic_link_limit_per_hour + 2):
        response = client.post("/v1/auth/magic-link", json={"email": "same@example.org"})
        assert response.status_code == 202
        assert response.json()["message"].startswith("If that address")
    assert len(mailer.deliveries) == settings.magic_link_limit_per_hour


@pytest.mark.spec("WEB-Q-002", "WEB-Q-003", "WEB-Q-004", "WEB-VOTE-005")
def test_signed_in_question_queue_tracks_history_votes_and_reports(
        client, mailer, session_factory):
    submitted = submit(client)
    cluster_id = approve(client, submitted.json()["submission_id"]).json()["cluster_id"]
    assert create_cycle(client).status_code == 201
    _, csrf = sign_in(client, mailer)

    page = client.get("/questions")
    assert page.status_code == 200
    assert "Send for review" in page.text and "Review decisions" in page.text
    assert "cannot be settled by a lookup" in page.text
    created = client.post("/v1/questions", json={
        "text": "How stable is this reported effect across preregistered replications?",
        "domain": "statistics"
    }, headers={"Idempotency-Key": "signed-in-question", "X-CSRF-Token": csrf})
    assert created.status_code == 201
    history = client.get("/v1/me/submissions").json()["submissions"]
    assert history[0]["moderation_state"] == "pending"
    assert history[0]["text"].startswith("How stable")
    pending = client.get("/v1/admin/submissions", headers=auth("moderator-2", "moderator"))
    assert created.json()["submission_id"] in {
        item["submission_id"] for item in pending.json()["submissions"]}

    assert client.put(f"/v1/questions/{cluster_id}/vote",
                      headers={"X-CSRF-Token": csrf}).status_code == 200
    queue = client.get("/v1/questions").json()
    assert queue["cycle"]["key"] == "2026-W40"
    assert queue["questions"][0]["viewer_has_voted"] is True

    body = {"reason": "misleading", "details": "The framing may imply a causal result."}
    first = client.post(f"/v1/questions/{cluster_id}/report", json=body,
                        headers={"X-CSRF-Token": csrf})
    replay = client.post(f"/v1/questions/{cluster_id}/report", json=body,
                         headers={"X-CSRF-Token": csrf})
    assert first.status_code == 201 and replay.json()["idempotent_replay"] is True
    moderator_headers = auth("moderator-2", "moderator")
    reports = client.get("/v1/admin/question-reports", headers=moderator_headers).json()["reports"]
    assert reports[0]["report_id"] == first.json()["report_id"]
    resolved = client.post(f"/v1/admin/question-reports/{first.json()['report_id']}/resolve",
                           json={"status": "dismissed", "reason": "Framing is within policy."},
                           headers=moderator_headers)
    assert resolved.json()["status"] == "dismissed"
    assert client.post(f"/v1/admin/question-reports/{first.json()['report_id']}/resolve",
                       json={"status": "resolved", "reason": "A later duplicate decision."},
                       headers=moderator_headers).json()["idempotent_replay"] is True
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(QuestionReport)) == 1
        assert session.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "question.reported")) == 1


@pytest.mark.spec("WEB-Q-002", "WEB-UI-001")
def test_question_queue_is_members_only(client):
    page = client.get("/questions", follow_redirects=False)
    assert page.status_code == 303 and page.headers["location"] == "/login?next=/questions"
    assert client.get("/v1/questions").status_code == 401
    cluster_id = approve(client, submit(client).json()["submission_id"]).json()["cluster_id"]
    create_cycle(client)
    client.put(f"/v1/questions/{cluster_id}/vote", headers=auth("voter-1"))
    home = client.get("/")
    assert "Does this treatment improve outcomes" not in home.text
    assert 'href="/questions"' not in home.text
    assert not re.search(r"\b\d+\s+(?:up)?votes?\b", home.text, re.I)


@pytest.mark.spec("WEB-Q-002", "WEB-Q-006")
def test_queue_groups_questions_by_domain_and_ranks_by_votes(client):
    ids = {}
    for key, (text, domain) in {
        "stats-a": ("When do bootstrap intervals undercover for heavy-tailed returns data?", "statistics"),
        "stats-b": ("How robust is the median-of-means estimator under contamination?", "statistics"),
        "econ-a": ("How sensitive are fiscal multipliers to the monetary policy regime?", "economics"),
    }.items():
        submission = submit(client, text, subject=f"asker-{key}", key=f"domain-{key}").json()
        ids[key] = approve(client, submission["submission_id"], domain=domain).json()["cluster_id"]
    create_cycle(client)
    client.put(f"/v1/questions/{ids['stats-b']}/vote", headers=auth("voter-1"))
    client.put(f"/v1/questions/{ids['stats-b']}/vote", headers=auth("voter-2"))
    client.put(f"/v1/questions/{ids['econ-a']}/vote", headers=auth("voter-1"))
    queue = client.get("/v1/questions", headers=auth("voter-1")).json()
    assert [item["key"] for item in queue["domains"]] == ["economics", "finance", "mathematics", "statistics"]
    order = [(item["domain"], item["cluster_id"], item["rank"]) for item in queue["questions"]]
    assert order == [("economics", ids["econ-a"], 1), ("statistics", ids["stats-b"], 1),
                     ("statistics", ids["stats-a"], 2)]
    by_id = {item["cluster_id"]: item for item in queue["questions"]}
    assert by_id[ids["stats-b"]]["votes"] == 2 and by_id[ids["stats-b"]]["domain_label"] == "Statistics"
    assert by_id[ids["econ-a"]]["viewer_has_voted"] is True
    assert by_id[ids["stats-a"]]["viewer_has_voted"] is False
