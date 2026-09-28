from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
import pytest

from conftest import approve, auth, submit
from orl_web.contracts import content_sha256, verify_checksum
from orl_web.models import AuditEvent, MetricsSnapshot


def make_metrics(stamp="20260926T170000Z", suffix="aaaaaaaaaaaa"):
    metric = lambda unit, name: {"value": 1, "unit": unit, "definition": f"Public {name} count."}
    payload = {
        "schema_version": "1", "snapshot_id": f"metrics-{stamp}-{suffix}",
        "generated_at": "2026-09-26T17:00:00Z", "corpus_snapshot": f"sha256:{'a' * 64}",
        "core_version": "0.1.0",
        "pipeline": {"index_version": 4, "embedding_model": "bge", "reranking_model": "reranker"},
        "metrics": {"papers": metric("papers", "papers"), "chunks": metric("chunks", "chunks"),
                    "equations": metric("equations", "equations"),
                    "references": metric("references", "references"),
                    "source_files": metric("files", "source files"),
                    "source_bytes": metric("bytes", "source bytes"),
                    "parsed_files": metric("files", "parsed files"),
                    "parsed_bytes": metric("bytes", "parsed bytes")},
        "dimensions": {"domain": [{"label": "biology", "count": 1}], "status": [], "evidence": []},
        "vector": {"backend": "qdrant", "total_chunks": 1, "indexed_chunks": 1,
                   "missing_chunks": 0, "coverage_ratio": 1.0, "sync_state": "current"},
    }
    payload["content_sha256"] = content_sha256(payload)
    return payload


@pytest.mark.spec("WEB-READY-001", "WEB-CONTRACT-001", "WEB-SEC-002")
def test_manual_readiness_is_validated_versioned_and_role_gated(client):
    submission = submit(client, key="readiness-question").json()
    cid = approve(client, submission["submission_id"]).json()["cluster_id"]
    now = datetime.now(UTC)
    body = {"assessment_id": "manual-assessment-1", "cluster_id": cid, "label": "moderate",
            "confidence": 0.7, "reasons": [{"code": "coverage_mixed", "summary": "Coverage is mixed."}],
            "corpus_snapshot": f"sha256:{'b' * 64}", "assessed_at": now.isoformat(),
            "expires_at": (now + timedelta(days=7)).isoformat()}
    assert client.post("/v1/admin/readiness", json=body, headers=auth("user-2")).status_code == 403
    saved = client.post("/v1/admin/readiness", json=body, headers=auth("editor-1", "editor"))
    assert saved.status_code == 201 and saved.json()["question_revision"] == 1
    public = client.get("/v1/questions", headers=auth()).json()["questions"][0]["readiness"]
    assert public["label"] == "moderate" and "user" not in str(public).lower()
    assert client.post("/v1/admin/readiness", json=body,
                       headers=auth("editor-1", "editor")).json() == saved.json()
    changed = {**body, "confidence": 0.2}
    assert client.post("/v1/admin/readiness", json=changed,
                       headers=auth("editor-1", "editor")).status_code == 409
    missing = {**body, "assessment_id": "missing-cluster", "cluster_id": "missing"}
    assert client.post("/v1/admin/readiness", json=missing,
                       headers=auth("editor-1", "editor")).status_code == 404
    backwards = {**body, "assessment_id": "backwards",
                 "expires_at": (now - timedelta(days=1)).isoformat()}
    assert client.post("/v1/admin/readiness", json=backwards,
                       headers=auth("editor-1", "editor")).status_code == 422
    bad_label = {**body, "assessment_id": "bad-label", "label": "certain"}
    assert client.post("/v1/admin/readiness", json=bad_label,
                       headers=auth("editor-1", "editor")).status_code == 422


@pytest.mark.spec("WEB-METRIC-001", "WEB-CONTRACT-001", "WEB-SEC-002")
def test_metrics_import_verifies_checksum_is_idempotent_and_serves_latest(client, session_factory):
    payload = make_metrics()
    assert verify_checksum(payload)
    assert client.post("/v1/admin/metrics", json=payload, headers=auth("editor-1", "editor")).status_code == 403
    imported = client.post("/v1/admin/metrics", json=payload, headers=auth("core-service", "service"))
    assert imported.status_code == 201
    assert client.post("/v1/admin/metrics", json=payload,
                       headers=auth("core-service", "service")).json() == payload
    assert client.get("/v1/metrics/latest").json() == payload
    with session_factory() as session:
        assert len(list(session.scalars(select(MetricsSnapshot)))) == 1
        event = session.scalar(select(AuditEvent).where(AuditEvent.action == "metrics.imported"))
        assert event.details == {"content_sha256": payload["content_sha256"]}


@pytest.mark.spec("WEB-CONTRACT-001")
def test_metrics_rejects_unknown_fields_and_tampering(client):
    assert client.get("/v1/metrics/latest").status_code == 404
    payload = make_metrics()
    damaged = {**payload, "private_path": "/core/catalog.db"}
    assert client.post("/v1/admin/metrics", json=damaged,
                       headers=auth("core-service", "service")).status_code == 422
    damaged = {**payload, "core_version": "9.9.9"}
    assert client.post("/v1/admin/metrics", json=damaged,
                       headers=auth("core-service", "service")).status_code == 422
    client.post("/v1/admin/metrics", json=payload, headers=auth("core-service", "service"))
    conflict = make_metrics()
    conflict["metrics"]["papers"]["value"] = 2
    conflict["content_sha256"] = content_sha256(conflict)
    assert client.post("/v1/admin/metrics", json=conflict,
                       headers=auth("core-service", "service")).status_code == 409
