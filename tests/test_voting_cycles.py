from __future__ import annotations

from sqlalchemy import func, select
import pytest

from datetime import UTC, datetime, timedelta

from conftest import approve, auth, create_cycle, submit
from orl_web.contracts import validate_contract
from orl_web.models import AuditEvent, CycleSelection, QuestionCluster, Vote, WeeklyCycle


def cluster(client, key, text, subject, domain="statistics"):
    submission = submit(client, text, subject=subject, key=key).json()
    return approve(client, submission["submission_id"], domain=domain).json()["cluster_id"]


def freeze(client, **body):
    return client.post("/v1/admin/cycles/2026-W40/freeze",
                       json={"reason": "Weekly voting cutoff reached.", **body},
                       headers=auth("admin-1", "admin"))


@pytest.mark.spec("WEB-DATA-002", "WEB-VOTE-005", "WEB-SEC-001")
def test_vote_create_remove_and_cluster_counts_are_idempotent(client, session_factory):
    cid = cluster(client, "vote-question", "Does exercise improve cognition in healthy older adults?", "asker")
    assert create_cycle(client).status_code == 201
    headers = auth("voter-1")
    first = client.put(f"/v1/questions/{cid}/vote", headers=headers)
    replay = client.put(f"/v1/questions/{cid}/vote", headers=headers)
    assert first.json()["idempotent_replay"] is False
    assert replay.json()["idempotent_replay"] is True
    assert client.get("/v1/questions", headers=headers).json()["questions"][0]["votes"] == 1
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Vote)) == 1
    assert client.delete(f"/v1/questions/{cid}/vote", headers=headers).status_code == 204
    assert client.delete(f"/v1/questions/{cid}/vote", headers=headers).status_code == 204
    with session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Vote)) == 0
        assert {x.action for x in session.scalars(select(AuditEvent).where(
            AuditEvent.target_id == cid))} >= {"vote.cast", "vote.removed"}


@pytest.mark.spec("WEB-CYCLE-001", "WEB-CONTRACT-001")
def test_cycle_freeze_records_reproducible_snapshot_and_contract(client, session_factory):
    first = cluster(client, "cycle-q-1", "Does intervention A reduce risk in adults over fifty?", "asker-1")
    second = cluster(client, "cycle-q-2", "Does intervention B reduce risk in adults over fifty?", "asker-2")
    create_cycle(client)
    client.put(f"/v1/questions/{second}/vote", headers=auth("voter-1"))
    client.put(f"/v1/questions/{second}/vote", headers=auth("voter-2"))
    client.put(f"/v1/questions/{first}/vote", headers=auth("voter-1"))
    frozen = freeze(client)
    assert frozen.status_code == 200
    body = frozen.json()
    assert [(item["domain"], item["cluster_id"], item["votes"]) for item in body["winners"]] == [
        ("statistics", second, 2)]
    assert body["vote_snapshot"]["domains"]["statistics"][0] == {"cluster_id": second, "votes": 2}
    assert body["vote_snapshot"]["winners"] == {"statistics": second}
    request = body["research_requests"][0]
    validate_contract("research-request", request)
    assert request["request_id"] == "weekly-2026-W40-statistics" and request["cluster_id"] == second
    replay = client.post("/v1/admin/cycles/2026-W40/freeze",
                         json={"reason": "Retry after response loss."}, headers=auth("admin-1", "admin"))
    assert replay.json()["idempotent_replay"] is True
    assert replay.json()["research_requests"] == body["research_requests"]
    with session_factory() as session:
        cycle = session.scalar(select(WeeklyCycle))
        assert cycle.vote_snapshot == body["vote_snapshot"]
        assert [(row.domain, row.cluster_id) for row in session.scalars(select(CycleSelection))] == [
            ("statistics", second)]
        assert session.get(QuestionCluster, second).public_status.value == "selected"
        assert session.get(QuestionCluster, first).public_status.value == "open"


@pytest.mark.spec("WEB-CYCLE-001", "WEB-Q-006")
def test_freeze_selects_the_most_upvoted_question_in_each_domain(client, session_factory):
    stats_low = cluster(client, "domain-q-1", "When do bootstrap intervals undercover for skewed data?", "a-1")
    stats_high = cluster(client, "domain-q-2", "How robust is the median-of-means estimator to outliers?", "a-2")
    econ = cluster(client, "domain-q-3", "How large are fiscal multipliers at the zero lower bound?", "a-3",
                   domain="economics")
    finance_unvoted = cluster(client, "domain-q-4", "Do momentum returns survive publication and trading costs?",
                              "a-4", domain="finance")
    create_cycle(client)
    client.put(f"/v1/questions/{stats_low}/vote", headers=auth("voter-1"))
    for voter in ("voter-1", "voter-2"):
        client.put(f"/v1/questions/{stats_high}/vote", headers=auth(voter))
    client.put(f"/v1/questions/{econ}/vote", headers=auth("voter-3"))
    body = freeze(client).json()
    assert {item["domain"]: item["cluster_id"] for item in body["winners"]} == {
        "economics": econ, "statistics": stats_high}
    assert {item["request_id"] for item in body["research_requests"]} == {
        "weekly-2026-W40-economics", "weekly-2026-W40-statistics"}
    assert body["vote_snapshot"]["domains"]["finance"] == [{"cluster_id": finance_unvoted, "votes": 0}]
    assert body["vote_snapshot"]["minimum_votes"] == 1
    with session_factory() as session:
        assert session.get(QuestionCluster, finance_unvoted).public_status.value == "open"
    listed = client.get("/v1/admin/cycles", headers=auth("admin-1", "admin")).json()["cycles"]
    assert listed[0]["cycle"] == "2026-W40" and len(listed[0]["winners"]) == 2
    assert client.get("/v1/admin/cycles", headers=auth("mod-1", "moderator")).status_code == 403


@pytest.mark.spec("WEB-CYCLE-002", "WEB-SEC-002")
def test_manual_override_requires_admin_reason_and_is_audited(client, session_factory):
    first = cluster(client, "override-q-1", "Should policy A be adopted for urban transport systems?", "asker-1")
    second = cluster(client, "override-q-2", "Should policy B be adopted for urban transport systems?", "asker-2")
    other = cluster(client, "override-q-3", "Should policy C be adopted for rural transport systems?", "asker-3",
                    domain="economics")
    create_cycle(client)
    client.put(f"/v1/questions/{second}/vote", headers=auth("voter-1"))
    assert freeze(client, reason="x", override_cluster_ids=[first]).status_code == 422
    assert freeze(client, override_cluster_ids=[first, second]).json()["detail"] == \
        "at most one override per domain"
    assert freeze(client, override_cluster_ids=["missing"]).status_code == 422
    assert client.post("/v1/admin/cycles/2026-W40/freeze",
                       json={"reason": "Editorial scope.", "override_cluster_ids": [first]},
                       headers=auth("mod-1", "moderator")).status_code == 403
    frozen = freeze(client, reason="Editorial scope requirement documented publicly.",
                    override_cluster_ids=[first, other])
    winners = {item["domain"]: item for item in frozen.json()["winners"]}
    assert winners["statistics"]["cluster_id"] == first and winners["statistics"]["override"] is True
    assert winners["economics"]["cluster_id"] == other and winners["economics"]["votes"] == 0
    assert frozen.json()["vote_snapshot"]["overrides"] == [first, other]
    with session_factory() as session:
        event = session.scalar(select(AuditEvent).where(AuditEvent.action == "cycle.frozen"))
        assert event.details["override"] is True and "scope" in event.details["reason"]
        assert event.details["winners"] == {"economics": other, "statistics": first}


def test_cycle_and_vote_failure_paths(client):
    cid = cluster(client, "failure-q-1", "Does sleep duration affect memory in healthy adults?", "asker")
    assert client.put(f"/v1/questions/{cid}/vote", headers=auth("voter")).status_code == 409
    now = datetime.now(UTC)
    invalid = client.post("/v1/admin/cycles", json={"cycle_key": "2026-W40",
                          "starts_at": now.isoformat(), "ends_at": (now - timedelta(days=1)).isoformat()},
                          headers=auth("admin-1", "admin"))
    assert invalid.status_code == 422
    assert create_cycle(client).status_code == 201
    assert create_cycle(client).json()["idempotent_replay"] is True
    other = client.post("/v1/admin/cycles", json={"cycle_key": "2026-W41",
                        "starts_at": now.isoformat(), "ends_at": (now + timedelta(days=7)).isoformat()},
                        headers=auth("admin-1", "admin"))
    assert other.status_code == 409
    assert client.put("/v1/questions/missing/vote", headers=auth("voter")).status_code == 404
    assert client.post("/v1/admin/cycles/missing/freeze", json={"reason": "Weekly cutoff."},
                       headers=auth("admin-1", "admin")).status_code == 404


@pytest.mark.spec("WEB-Q-006", "WEB-CYCLE-001")
def test_questions_from_before_domains_form_an_unassigned_group(client, session_factory):
    with session_factory() as session:
        legacy = QuestionCluster(canonical_question="Does an older question keep its place in the queue?",
                                 tags=["legacy"])
        session.add(legacy)
        session.commit()
        legacy_id = legacy.id
    create_cycle(client)
    client.put(f"/v1/questions/{legacy_id}/vote", headers=auth("voter-1"))
    queue = client.get("/v1/questions", headers=auth("voter-1")).json()
    assert queue["domains"][-1] == {"key": "unassigned", "label": "Unassigned"}
    assert queue["questions"][0]["domain"] == "unassigned" and queue["questions"][0]["rank"] == 1
    body = freeze(client).json()
    assert body["winners"][0]["domain_label"] == "Unassigned"
    assert body["research_requests"][0]["request_id"] == "weekly-2026-W40-unassigned"
