from __future__ import annotations

import os

# Hermetic suite: a developer's orl-web/.env or exported ORL_WEB_* variables must never reach the
# tests. In particular ORL_WEB_DATABASE_URL would point the migration test at a real database.
for _name in [name for name in os.environ if name.startswith("ORL_WEB_")]:
    del os.environ[_name]
os.environ["ORL_WEB_DOTENV"] = "0"

from datetime import UTC, datetime, timedelta

import jwt
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from orl_web.app import create_app
from orl_web.config import Settings
from orl_web.contracts import content_sha256
from orl_web.models import Base


SECRET = "test-secret-that-is-long-enough-for-hs256"


class CaptureMailer:
    def __init__(self):
        self.deliveries = []
        self.approvals = []

    def send(self, email, verify_url):
        self.deliveries.append((email, verify_url))

    def send_access_approved(self, email, sign_in_url):
        self.approvals.append((email, sign_in_url))


@pytest.fixture
def session_factory():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False},
                           poolclass=StaticPool)
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)
    yield factory
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture
def settings():
    return Settings(jwt_secret=SECRET, question_limit_per_hour=5, vote_limit_per_hour=10)


@pytest.fixture
def mailer():
    return CaptureMailer()


@pytest.fixture
def client(session_factory, settings, mailer):
    with TestClient(create_app(settings=settings, session_factory=session_factory,
                               mailer=mailer)) as value:
        yield value


def token(subject="user-1", role="user", *, settings=None, expired=False):
    settings = settings or Settings(jwt_secret=SECRET)
    now = datetime.now(UTC)
    return jwt.encode({"sub": subject, "role": role, "iat": now,
                       "exp": now + (-timedelta(minutes=1) if expired else timedelta(hours=1)),
                       "iss": settings.jwt_issuer, "aud": settings.jwt_audience},
                      settings.jwt_secret, algorithm="HS256")


def auth(subject="user-1", role="user"):
    return {"Authorization": f"Bearer {token(subject, role)}"}


def submit(client, text="Does this treatment improve outcomes across diverse adult populations?",
           subject="user-1", key="submission-key-1"):
    return client.post("/v1/questions", json={"text": text},
                       headers={**auth(subject), "Idempotency-Key": key})


def grant_access(client, email):
    return client.post("/v1/admin/access", json={"email": email, "reason": "Early-access cohort."},
                       headers=auth("admin-1", "admin"))


def approve(client, submission_id, *, cluster_id=None, domain="statistics", subject="moderator-1"):
    body = {"action": "approve", "reason": "Within scope and suitable for research."}
    if cluster_id:
        body["cluster_id"] = cluster_id
    elif domain:
        body["domain"] = domain
    return client.post(f"/v1/admin/submissions/{submission_id}/moderate", json=body,
                       headers=auth(subject, "moderator"))


def create_cycle(client, key="2026-W40"):
    now = datetime.now(UTC)
    return client.post("/v1/admin/cycles", json={"cycle_key": key,
                       "starts_at": (now - timedelta(days=1)).isoformat(),
                       "ends_at": (now + timedelta(days=6)).isoformat()},
                       headers=auth("admin-1", "admin"))


def publication_bundle(slug="does-the-effect-hold", bundle_id="bundle-1", *, revision=1,
                       supersedes_bundle_id=None, correction_summary=""):
    payload = {
        "schema_version": "1", "bundle_id": bundle_id, "request_id": "weekly-2026-W40",
        "cluster_id": "cluster-public", "revision": revision,
        "supersedes_bundle_id": supersedes_bundle_id,
        "correction_summary": correction_summary, "created_at": "2026-09-26T17:00:00Z",
        "article": {
            "title": "Does the effect hold outside the original sample?", "slug": slug,
            "summary": "The evidence supports a narrower conclusion than the headline result suggests.",
            "markdown": "## Direct answer\n\nThe effect appears **conditional**, not universal. [C1] "
                        "Across settings, design choices materially change the estimate.\n\n"
                        "<script>alert('never execute')</script>\n\n## What changes the conclusion\n\n"
                        "Better preregistered replications would reduce the remaining uncertainty."
        },
        "research_record": {
            "question": "Does the reported effect replicate outside the original sample?",
            "scope": {"statement": "Compare the reported effect across populations and designs.",
                      "assumptions": ["Outcome definitions are sufficiently comparable"]},
            "methodology": [
                {"stage": "Retrieval and screening", "status": "complete",
                 "summary": "Combined semantic and lexical retrieval, then screened for direct relevance.",
                 "tools": ["hybrid retrieval", "cross-encoder reranking"]},
                {"stage": "Statistical stress test", "status": "partial",
                 "summary": "Compared effect direction and uncertainty where compatible data were available.",
                 "tools": ["meta-analytic sensitivity check"]}
            ],
            "expert_contributions": [
                {"expert": "statistics", "role": "Statistical reviewer",
                 "perspective": "Examined uncertainty, selection, and cross-study comparability.",
                 "findings": ["Reported effects are heterogeneous."]},
                {"expert": "methodology", "role": "Design critic",
                 "perspective": "Tested whether design changes explain divergent findings.",
                 "findings": ["Measurement choices matter materially."]}
            ],
            "research_log": [
                {"sequence": 1, "actor": "research_director", "action": "Defined answerability criteria",
                 "status": "complete", "summary": "Required independent samples and comparable outcomes.",
                 "evidence_refs": []},
                {"sequence": 2, "actor": "statistics", "action": "Audited effect stability",
                 "status": "complete", "summary": "Compared direction and interval width across studies.",
                 "evidence_refs": ["C1", "C2"]}
            ],
            "evidence_map": [
                {"claim": "The effect is not stable across all studied settings.", "verdict": "supported",
                 "supporting_citations": ["C1", "C2"], "contradicting_citations": []}
            ],
            "disagreements": [{"question": "How much heterogeneity is substantive?",
                "positions": [
                    {"expert": "statistics", "position": "Intervals imply meaningful instability."},
                    {"expert": "methodology", "position": "Some variation follows expected design differences."}
                ], "resolution": "The article reports both interpretations and narrows its conclusion."}],
            "computations": [{"name": "Cross-study sensitivity check",
                "method": "Recomputed a standardized range under common assumptions.",
                "inputs": "Published estimates and uncertainty intervals from C1 and C2.",
                "result": "The direction remained positive but magnitude was unstable.",
                "reproducibility": "Inputs, transformations, and tolerance are retained in the Core audit."}],
            "limitations": ["Several studies use non-equivalent outcome measures."],
            "open_questions": ["Which preregistered design best distinguishes the competing explanations?"]
        },
        "citations": [
            {"citation_id": "C1", "title": "Original effect study", "authors": ["A. Researcher"],
             "year": 2020, "doi": "10.1000/original", "url": None},
            {"citation_id": "C2", "title": "Independent replication", "authors": ["B. Scientist"],
             "year": 2024, "doi": "10.1000/replication", "url": None}
        ],
        "gates": [
            {"name": name, "passed": name != "editorial_review", "version": "1",
             "summary": "Passed Core review." if name != "editorial_review" else "Pending editor."}
            for name in ("research_review", "citation_support", "originality", "copyright", "equation_validation",
                         "quantitative_validation", "editorial_review")
        ]
    }
    payload["content_sha256"] = content_sha256(payload)
    return payload
