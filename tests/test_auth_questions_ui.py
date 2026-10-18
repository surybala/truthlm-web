from __future__ import annotations

import re
from urllib.parse import parse_qs, urlsplit

import pytest
from sqlalchemy import func, select

from orl_web.models import (AuditEvent, BrowserSession, MagicLinkToken, QuestionCluster,
                            QuestionReport, User)

from conftest import approve, auth, grant_access, submit


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
    redirected = client.get("/login?next=//evil.example/path", follow_redirects=False)
    assert redirected.status_code == 303 and redirected.headers["location"] == "/questions"
    backslash = client.get("/login?next=/%5Cevil.example/path", follow_redirects=False)
    assert backslash.status_code == 303 and backslash.headers["location"] == "/questions"
    safe = client.get("/login?next=/questions", follow_redirects=False)
    assert safe.status_code == 303 and safe.headers["location"] == "/questions"
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
        "Idempotency-Key": "browser-question-1", "X-CSRF-Token": csrf}).status_code == 403
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


@pytest.mark.spec("WEB-Q-001", "WEB-Q-002")
def test_question_workspace_is_for_the_editorial_team(client):
    member_page = client.get("/questions", headers=auth("member", "user"), follow_redirects=False)
    assert member_page.status_code == 303 and member_page.headers["location"] == "/subscriptions"
    moderator_page = client.get("/questions", headers=auth("mod-1", "moderator"), follow_redirects=False)
    assert moderator_page.status_code == 303

    editor_page = client.get("/questions", headers=auth("owner", "editor"))
    assert editor_page.status_code == 200
    for copy in ("Research questions", "Submit a research question", "Approved questions",
                 "Your submissions"):
        assert copy in editor_page.text
    for removed in ("Private research", "paid", "Coming soon", "Upvote", "ranked by"):
        assert removed not in editor_page.text
    for label in ("Biology", "Chemistry", "Physics"):
        assert f">{label}</option>" in editor_page.text

    question = {"text": "How stable is this reported effect across preregistered replications?",
                "domain": "statistics"}
    for role in ("user", "moderator", "paid"):
        denied = client.post("/v1/questions", json=question,
                             headers={**auth("someone", role), "Idempotency-Key": f"denied-{role}"})
        assert denied.status_code == (401 if role == "paid" else 403)
    created = client.post("/v1/questions", json=question,
                          headers={**auth("admin-1", "admin"), "Idempotency-Key": "admin-question"})
    assert created.status_code == 201
    history = client.get("/v1/me/submissions", headers=auth("admin-1", "admin")).json()["submissions"]
    assert history[0]["text"] == question["text"] and history[0]["moderation_state"] == "pending"
    assert "answer" not in history[0] and "answered_at" not in history[0]
    assert client.put(f"/v1/admin/submissions/{created.json()['submission_id']}/answer",
                      json={"answer": "A private answer is no longer part of TruthLM."},
                      headers=auth("owner", "editor")).status_code in {404, 405}


@pytest.mark.spec("WEB-Q-003", "WEB-Q-004", "WEB-SEC-002")
def test_members_report_questions_and_moderators_resolve_each_once(client, session_factory):
    cluster_id = approve(client, submit(client).json()["submission_id"]).json()["cluster_id"]
    report = {"reason": "misleading", "details": "The wording assumes the effect exists."}
    assert client.post(f"/v1/questions/{cluster_id}/report", json=report).status_code == 401
    assert client.post("/v1/questions/missing/report", json=report,
                       headers=auth("member-1")).status_code == 404
    assert client.post(f"/v1/questions/{cluster_id}/report", json={"reason": "boring"},
                       headers=auth("member-1")).status_code == 422
    first = client.post(f"/v1/questions/{cluster_id}/report", json=report, headers=auth("member-1"))
    assert first.status_code == 201 and first.json()["idempotent_replay"] is False
    replay = client.post(f"/v1/questions/{cluster_id}/report", json=report, headers=auth("member-1"))
    assert replay.json() == {**first.json(), "idempotent_replay": True}

    assert client.get("/v1/admin/question-reports", headers=auth("member-1")).status_code == 403
    listed = client.get("/v1/admin/question-reports", headers=auth("mod-1", "moderator")).json()
    assert [(item["question"], item["reason"]) for item in listed["reports"]] == [
        ("Does this treatment improve outcomes across diverse adult populations?", "misleading")]
    resolve = f"/v1/admin/question-reports/{first.json()['report_id']}/resolve"
    assert client.post("/v1/admin/question-reports/missing/resolve",
                       json={"status": "resolved", "reason": "Reworded the question."},
                       headers=auth("mod-1", "moderator")).status_code == 404
    resolved = client.post(resolve, json={"status": "resolved", "reason": "Reworded the question."},
                           headers=auth("mod-1", "moderator"))
    assert resolved.json()["status"] == "resolved" and resolved.json()["idempotent_replay"] is False
    again = client.post(resolve, json={"status": "dismissed", "reason": "Changed my mind."},
                        headers=auth("mod-1", "moderator"))
    assert again.json()["status"] == "resolved" and again.json()["idempotent_replay"] is True
    assert client.get("/v1/admin/question-reports", headers=auth("mod-1", "moderator")).json()[
        "reports"] == []
    closed = client.get("/v1/admin/question-reports?status=resolved",
                        headers=auth("mod-1", "moderator")).json()["reports"]
    assert closed[0]["resolution"] == "Reworded the question." and closed[0]["resolved_at"]
    with session_factory() as session:
        assert session.scalar(select(QuestionReport)).status == "resolved"
        actions = {event.action for event in session.scalars(select(AuditEvent))}
        assert {"question.reported", "question.report_resolved"} <= actions


@pytest.mark.spec("WEB-Q-002", "WEB-UI-001")
def test_question_list_is_members_only_and_never_public(client):
    page = client.get("/questions", follow_redirects=False)
    assert page.status_code == 303 and page.headers["location"] == "/login?next=/questions"
    assert client.get("/v1/questions").status_code == 401
    approve(client, submit(client).json()["submission_id"])
    assert client.put("/v1/questions/anything/vote", headers=auth("member-1")).status_code in {404, 405}
    home = client.get("/")
    assert "Does this treatment improve outcomes" not in home.text
    assert 'href="/questions"' not in home.text
    assert not re.search(r"\b\d+\s+(?:up)?votes?\b", home.text, re.I)


@pytest.mark.spec("WEB-Q-002", "WEB-Q-006")
def test_question_list_groups_by_domain_oldest_first(client, session_factory):
    with session_factory() as session:
        legacy = QuestionCluster(canonical_question="Does an older question keep its place in the list?",
                                 tags=["legacy"])
        session.add(legacy)
        session.commit()
        legacy_id = legacy.id
    ids = {}
    for key, (text, domain) in {
        "stats-a": ("When do bootstrap intervals undercover for heavy-tailed returns data?", "statistics"),
        "stats-b": ("How robust is the median-of-means estimator under contamination?", "statistics"),
        "econ-a": ("How sensitive are fiscal multipliers to the monetary policy regime?", "economics"),
    }.items():
        submission = submit(client, text, subject=f"asker-{key}", key=f"domain-{key}").json()
        ids[key] = approve(client, submission["submission_id"], domain=domain).json()["cluster_id"]
    listed = client.get("/v1/questions", headers=auth("member-1")).json()
    assert [item["key"] for item in listed["domains"]] == [
        "biology", "chemistry", "economics", "finance", "mathematics", "physics", "statistics",
        "unassigned"]
    assert listed["domains"][-1] == {"key": "unassigned", "label": "Unassigned"}
    assert [(item["domain"], item["cluster_id"]) for item in listed["questions"]] == [
        ("economics", ids["econ-a"]), ("statistics", ids["stats-a"]), ("statistics", ids["stats-b"]),
        ("unassigned", legacy_id)]
    item = listed["questions"][0]
    assert item["domain_label"] == "Economics" and item["status"] == "open"
    assert item["readiness"] is None
    assert not {"votes", "rank", "viewer_has_voted"} & set(item)
    assert "cycle" not in listed
