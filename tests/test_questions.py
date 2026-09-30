from __future__ import annotations

from sqlalchemy import func, select
import pytest

from conftest import approve, auth, submit, token
from orl_web.models import AuditEvent, ClusterMembership, QuestionCluster, QuestionSubmission


@pytest.mark.spec("WEB-SEC-001")
def test_health_and_authentication_boundary(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    home = client.get("/")
    assert home.status_code == 200
    assert "TruthLM" in home.text
    assert client.post("/v1/questions", json={"text": "A sufficiently long research question here."},
                       headers={"Idempotency-Key": "abcdefgh"}).status_code == 401
    assert client.post("/v1/questions", json={"text": "too short"},
                       headers={**auth(role="paid"), "Idempotency-Key": "abcdefgh"}).status_code == 422
    expired = {"Authorization": f"Bearer {token(expired=True)}", "Idempotency-Key": "abcdefgh"}
    assert client.post("/v1/questions", json={
        "text": "A sufficiently long research question here."}, headers=expired).status_code == 401
    assert client.post("/v1/questions", json={
        "text": "A sufficiently long research question here."},
        headers={**auth(role="user"), "Idempotency-Key": "user-tier"}).status_code == 403
    assert client.post("/v1/questions", json={
        "text": "A sufficiently long research question here."},
        headers={**auth(role="paid"), "Idempotency-Key": "short"}).status_code == 400


@pytest.mark.spec("WEB-Q-001")
def test_submission_retains_original_normalizes_and_is_idempotent(client, session_factory):
    original = "Does\u00a0 this   treatment improve outcomes across diverse adult populations?"
    first = submit(client, original).json()
    replay = submit(client, "different wording but same key").json()
    assert first["submission_id"] == replay["submission_id"] and replay["idempotent_replay"]
    with session_factory() as session:
        item = session.get(QuestionSubmission, first["submission_id"])
        assert item.original_text == original
        assert item.normalized_text == "Does this treatment improve outcomes across diverse adult populations?"


@pytest.mark.spec("WEB-Q-001", "WEB-SEC-001")
def test_submission_rate_limit_is_per_user(client):
    for number in range(5):
        response = submit(client, subject="limited-user", key=f"rate-key-{number}")
        assert response.status_code == 201
    blocked = submit(client, subject="limited-user", key="rate-key-blocked")
    assert blocked.status_code == 429
    assert submit(client, subject="other-user", key="rate-key-other").status_code == 201


@pytest.mark.spec("WEB-Q-005", "WEB-SEC-002")
def test_manual_moderation_groups_without_erasing_originals(client, session_factory):
    one = submit(client, "Does vitamin D improve respiratory outcomes in older adults?",
                 key="vitamin-question-1").json()
    cluster = approve(client, one["submission_id"]).json()["cluster_id"]
    two = submit(client, "Can vitamin D help respiratory health among elderly people?",
                 subject="user-2", key="vitamin-question-2").json()
    grouped = approve(client, two["submission_id"], cluster_id=cluster).json()
    assert grouped["cluster_id"] == cluster
    assert approve(client, two["submission_id"], cluster_id=cluster).json()["idempotent_replay"]
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(ClusterMembership)) == 2
        assert session.scalar(select(func.count()).select_from(AuditEvent).where(
            AuditEvent.action == "question.approved")) == 2
        originals = list(session.scalars(select(QuestionSubmission.original_text)))
        assert len(originals) == 2 and originals[0] != originals[1]


@pytest.mark.spec("WEB-Q-005", "WEB-SEC-002")
def test_rejection_and_role_separation_are_audited(client, session_factory):
    item = submit(client, key="reject-key-1").json()
    forbidden = client.post(f"/v1/admin/submissions/{item['submission_id']}/moderate",
                            json={"action": "reject", "reason": "Outside published scope."},
                            headers=auth("ordinary-user", "user"))
    assert forbidden.status_code == 403
    rejected = client.post(f"/v1/admin/submissions/{item['submission_id']}/moderate",
                           json={"action": "reject", "reason": "Outside published scope."},
                           headers=auth("moderator-1", "moderator"))
    assert rejected.status_code == 200 and rejected.json()["state"] == "rejected"
    with session_factory() as session:
        event = session.scalar(select(AuditEvent).where(AuditEvent.action == "question.rejected"))
        assert event.details["reason"] == "Outside published scope."


def test_moderation_rejects_missing_and_invalid_cluster_assignments(client):
    assert client.post("/v1/admin/submissions/missing/moderate",
                       json={"action": "reject", "reason": "Outside scope."},
                       headers=auth("moderator-1", "moderator")).status_code == 404
    item = submit(client, key="invalid-cluster-key").json()
    assert client.post(f"/v1/admin/submissions/{item['submission_id']}/moderate",
                       json={"action": "approve", "reason": "Manual grouping decision.",
                             "cluster_id": "missing"},
                       headers=auth("moderator-1", "moderator")).status_code == 404
    assert client.post(f"/v1/admin/submissions/{item['submission_id']}/moderate",
                       json={"action": "reject", "reason": "Outside scope.",
                             "cluster_id": "not-allowed"},
                       headers=auth("moderator-1", "moderator")).status_code == 422


@pytest.mark.spec("WEB-Q-006")
def test_domains_are_suggested_by_submitters_and_assigned_by_moderators(client, session_factory):
    unknown = client.post("/v1/questions", json={
        "text": "Does quantum annealing beat classical heuristics on scheduling problems?",
        "domain": "physics"}, headers={**auth(role="paid"), "Idempotency-Key": "unknown-domain"})
    assert unknown.status_code == 422
    suggested = client.post("/v1/questions", json={
        "text": "Do fiscal multipliers differ between recessions and expansions?",
        "domain": "economics"}, headers={**auth(role="paid"), "Idempotency-Key": "suggested-domain"}).json()
    listed = client.get("/v1/admin/submissions", headers=auth("moderator-1", "moderator")).json()
    assert listed["submissions"][0]["suggested_domain_label"] == "Economics"
    kept = approve(client, suggested["submission_id"], domain=None).json()
    missing = submit(client, "How should we estimate tail risk in short return samples?",
                     key="no-domain-question").json()
    moderate = f"/v1/admin/submissions/{missing['submission_id']}/moderate"
    headers = auth("moderator-1", "moderator")
    assert approve(client, missing["submission_id"], domain=None).status_code == 422
    assert approve(client, missing["submission_id"], domain="biology").status_code == 422
    assert client.post(moderate, json={"action": "approve", "reason": "Same question.",
                                       "cluster_id": kept["cluster_id"], "domain": "finance"},
                       headers=headers).status_code == 422
    assert client.post(moderate, json={"action": "reject", "reason": "Outside scope.",
                                       "domain": "finance"}, headers=headers).status_code == 422
    attached = approve(client, missing["submission_id"], cluster_id=kept["cluster_id"]).json()
    assert attached["cluster_id"] == kept["cluster_id"]
    with session_factory() as session:
        cluster = session.get(QuestionCluster, kept["cluster_id"])
        assert cluster.domain == "economics"
        assert session.get(QuestionSubmission, suggested["submission_id"]).suggested_domain == "economics"


@pytest.mark.spec("WEB-Q-005", "WEB-Q-002")
def test_pending_questions_stay_private_and_rejection_reason_reaches_submitter(client):
    item = submit(client, "What is one plus two and why is the answer three?",
                  subject="asker-simple", key="simple-question").json()
    assert client.get("/v1/questions", headers=auth("member-2")).json()["questions"] == []
    reason = "This has a direct answer that a lookup or calculator can give."
    client.post(f"/v1/admin/submissions/{item['submission_id']}/moderate",
                json={"action": "reject", "reason": reason}, headers=auth("moderator-1", "moderator"))
    history = client.get("/v1/me/submissions", headers=auth("asker-simple")).json()["submissions"]
    assert history[0]["moderation_state"] == "rejected" and history[0]["moderation_reason"] == reason
    assert client.get("/v1/questions", headers=auth("member-2")).json()["questions"] == []
