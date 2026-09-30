from __future__ import annotations

import copy
import re
from html import unescape
from urllib.parse import parse_qs, urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from conftest import SECRET, CaptureMailer, auth, grant_access, publication_bundle
from orl_web.app import create_app
from orl_web.config import Settings
from orl_web.contracts import content_sha256
from orl_web.models import Article, ArticleRevision


@pytest.mark.spec("WEB-UI-001")
def test_public_home_and_method_explain_transparent_research(client):
    home = client.get("/")
    assert home.status_code == 200
    for expected in ("Questions before answers",
                     "Provides thoughtful, scientifically grounded answers after expert review",
                     "How TruthLM turns a question into grounded research", "Research director",
                     "Domain expert", "Research library", "Grounded LLM synthesis",
                     "Multi-round expert review", "Repeat until material issues are resolved",
                     "Expert-reviewed answer",
                     'aria-label="Pause animation"',
                     "Join the waitlist", 'id="join-form"'):
        assert expected in home.text
    for removed in ("Seven questions every investigation must answer", "Who it is for",
                    "not a social network", "Read openly. Join when you are ready.",
                    "Whitelisted account"):
        assert removed not in home.text
    assert "TruthLM · A thought assistant for students and researchers" not in home.text
    for removed_badge in (">RD<", ">D<", ">E<", ">Q<", ">AI<"):
        assert removed_badge not in home.text
    assert 'href="/login">Sign in' in home.text and 'href="/questions"' not in home.text
    assert "frame-ancestors 'none'" in home.headers["content-security-policy"]
    assert home.headers["x-content-type-options"] == "nosniff"
    hero = client.get("/static/images/truthlm-research-workspace-v2.png")
    assert hero.status_code == 200
    assert hero.headers["content-type"] == "image/png"
    assert "We would rather publish nothing" in home.text
    archive = client.get("/research")
    assert 'class="feed-link" href="/join"' in archive.text
    assert "Subscribe to new research" in archive.text
    assert '>RSS feed</a>' not in archive.text
    method = client.get("/method")
    assert method.status_code == 200
    assert "reproducible record" in method.text
    assert "hidden chain-of-thought" not in method.text
    assert "Reviewed by people, prioritized by members" not in method.text
    assert method.text.count('class="ask-yourself"') == 7
    assert "answerable with a lookup or a calculator" not in method.text


@pytest.mark.spec("WEB-PUB-001", "WEB-PUB-002", "WEB-PUB-004", "WEB-PUB-005", "WEB-UI-001", "WEB-SEC-002")
def test_publication_import_publish_archive_and_research_record(client):
    payload = publication_bundle()
    imported = client.post("/v1/admin/publications", json=payload,
                           headers=auth("core-service", "service"))
    assert imported.status_code == 201 and imported.json()["status"] == "draft"
    assert client.post("/v1/admin/publications", json=payload,
                       headers=auth("core-service", "service")).json()["idempotent_replay"]
    assert "Does the effect" not in client.get("/research").text
    assert client.post("/v1/admin/publications/bundle-1/publish",
                       headers=auth("ordinary-user", "user")).status_code == 403
    published = client.post("/v1/admin/publications/bundle-1/publish",
                            headers=auth("editor-1", "editor"))
    assert published.status_code == 200 and published.json()["status"] == "published"
    assert client.post("/v1/admin/publications/bundle-1/publish",
                       headers=auth("editor-1", "editor")).json()["idempotent_replay"]

    home = client.get("/")
    assert "Does the effect" in home.text
    assert 'data-investigation-rail' in home.text
    assert 'data-count="1"' in home.text
    archive = client.get("/research")
    assert "Does the effect hold outside" in archive.text
    assert "Does the effect" in client.get("/research?q=effect").text
    assert "Does the effect" not in client.get("/research?q=unrelated").text
    article = client.get("/research/does-the-effect-hold")
    assert article.status_code == 200
    for expected in ("Findings", "Research record", "Evidence &amp; sources", "Retrieval and screening",
                     "What each expert brought", "Where the consortium did not converge",
                     "Cross-study sensitivity check", "Research journey", "How the answer earned its confidence",
                     "Editorial review and publication", "Technical audit trail", "2 timestamped events retained",
                     "Original effect study",
                     "cited papers"):
        assert expected in article.text
    assert "Ran search_library" not in article.text
    assert "Connected evidence:" not in article.text
    assert "View 2 connected evidence records" in article.text
    assert "&lt;script&gt;alert" in article.text and "<script>alert" not in article.text
    assert client.get("/v1/articles").json()["articles"][0]["slug"] == "does-the-effect-hold"
    assert client.get("/research/missing").status_code == 404


def test_article_references_only_show_unique_papers_with_bibliographic_metadata(client):
    payload = publication_bundle(bundle_id="bundle-references", slug="clean-references")
    payload["citations"] += [
        {"citation_id": "S1", "title": 'OpenAlex literature search "short sample" (2026-09-27): 0 results',
         "authors": ["ORL source"], "year": None, "doi": None, "url": None},
        {"citation_id": "D1", "title": "FRED market data pull", "authors": ["ORL source"],
         "year": None, "doi": None, "url": "https://fred.stlouisfed.org/"},
        copy.deepcopy(payload["citations"][0]),
    ]
    payload["citations"][-1]["citation_id"] = "C3"
    payload["content_sha256"] = content_sha256(payload)
    assert client.post("/v1/admin/publications", json=payload,
                       headers=auth("core-service", "service")).status_code == 201
    assert client.post("/v1/admin/publications/bundle-references/publish",
                       headers=auth("editor-1", "editor")).status_code == 200

    article = client.get("/research/clean-references")
    assert article.status_code == 200
    assert "2 cited papers" in article.text
    assert article.text.count("Original effect study") == 2
    assert "OpenAlex literature search" not in article.text
    assert "FRED market data pull" not in article.text
    assert ">C1, C3<" in article.text


@pytest.mark.spec("WEB-PUB-001", "WEB-PUB-004", "WEB-CONTRACT-001")
def test_publication_rejects_tampering_failed_gates_and_unstructured_reasoning(client):
    payload = publication_bundle()
    tampered = {**payload, "content_sha256": "0" * 64}
    assert client.post("/v1/admin/publications", json=tampered,
                       headers=auth("core-service", "service")).status_code == 422

    failed = publication_bundle(bundle_id="bundle-failed", slug="failed-gate")
    next(gate for gate in failed["gates"] if gate["name"] == "copyright")["passed"] = False
    failed["content_sha256"] = content_sha256(failed)
    response = client.post("/v1/admin/publications", json=failed,
                           headers=auth("core-service", "service"))
    assert response.status_code == 422 and "copyright" in response.json()["detail"]

    unresolved = publication_bundle(bundle_id="bundle-unresolved", slug="unresolved-review")
    next(gate for gate in unresolved["gates"] if gate["name"] == "research_review")["passed"] = False
    unresolved["content_sha256"] = content_sha256(unresolved)
    response = client.post("/v1/admin/publications", json=unresolved,
                           headers=auth("core-service", "service"))
    assert response.status_code == 422 and "research_review" in response.json()["detail"]

    unknown = publication_bundle(bundle_id="bundle-unknown", slug="unknown-citation")
    unknown["research_record"]["research_log"][0]["evidence_refs"] = ["C999"]
    unknown["content_sha256"] = content_sha256(unknown)
    response = client.post("/v1/admin/publications", json=unknown,
                           headers=auth("core-service", "service"))
    assert response.status_code == 422 and "C999" in response.json()["detail"]

    unstructured = copy.deepcopy(publication_bundle(bundle_id="bundle-cot", slug="raw-reasoning"))
    unstructured["research_record"]["chain_of_thought"] = "private token-by-token reasoning"
    unstructured["content_sha256"] = content_sha256(unstructured)
    assert client.post("/v1/admin/publications", json=unstructured,
                       headers=auth("core-service", "service")).status_code == 422

    unsafe_url = publication_bundle(bundle_id="bundle-url", slug="unsafe-citation-url")
    unsafe_url["citations"][0]["url"] = "javascript:alert(1)"
    unsafe_url["content_sha256"] = content_sha256(unsafe_url)
    response = client.post("/v1/admin/publications", json=unsafe_url,
                           headers=auth("core-service", "service"))
    assert response.status_code == 422 and "http or https" in response.json()["detail"]

    duplicate_citation = publication_bundle(bundle_id="bundle-duplicate", slug="duplicate-citation")
    duplicate_citation["citations"].append(copy.deepcopy(duplicate_citation["citations"][0]))
    duplicate_citation["content_sha256"] = content_sha256(duplicate_citation)
    response = client.post("/v1/admin/publications", json=duplicate_citation,
                           headers=auth("core-service", "service"))
    assert response.status_code == 422 and "citation IDs" in response.json()["detail"]


@pytest.mark.spec("WEB-PUB-001", "WEB-PUB-003", "WEB-EDIT-001", "WEB-SEC-002")
def test_editorial_queue_corrections_rejections_and_retraction_history(client, session_factory):
    editor_page = client.get("/editor")
    assert editor_page.status_code == 200 and "Review the record" in editor_page.text
    assert client.get("/v1/admin/publications").status_code == 401
    assert client.get("/v1/admin/publications", headers=auth("user", "user")).status_code == 403

    first = publication_bundle()
    assert client.post("/v1/admin/publications", json=first,
                       headers=auth("core", "service")).status_code == 201
    queue = client.get("/v1/admin/publications", headers=auth("editor", "editor")).json()
    assert queue["publications"][0]["status"] == "draft"
    detail = client.get("/v1/admin/publications/bundle-1",
                        headers=auth("editor", "editor")).json()
    assert detail["research_record"]["methodology"] and detail["gates"]
    assert client.post("/v1/admin/publications/bundle-1/publish",
                       headers=auth("editor", "editor")).status_code == 200

    correction = publication_bundle(bundle_id="bundle-2", revision=2,
                                    supersedes_bundle_id="bundle-1",
                                    correction_summary="Clarified the population boundary.")
    correction["article"]["summary"] = "A corrected summary with a narrower population boundary."
    correction["content_sha256"] = content_sha256(correction)
    imported = client.post("/v1/admin/publications", json=correction,
                           headers=auth("core", "service"))
    assert imported.status_code == 201 and imported.json()["revision"] == 2
    assert client.post("/v1/admin/publications/bundle-2/publish",
                       headers=auth("editor", "editor")).status_code == 200

    public = client.get("/research/does-the-effect-hold")
    assert '<aside class="correction-banner">' not in public.text
    assert "Clarified the population boundary." in public.text
    assert "Publication history" in public.text and "Revision 1" in public.text
    with session_factory() as session:
        article = session.scalar(select(Article).where(Article.slug == "does-the-effect-hold"))
        revisions = list(session.scalars(select(ArticleRevision).where(
            ArticleRevision.article_id == article.id).order_by(ArticleRevision.revision)))
        assert article.bundle_id == "bundle-2"
        assert [item.status for item in revisions] == ["superseded", "published"]

    reason = {"reason": "A material data error invalidated the central estimate."}
    retracted = client.post("/v1/admin/publications/bundle-2/retract", json=reason,
                            headers=auth("editor", "editor"))
    assert retracted.status_code == 200
    tombstone = client.get("/research/does-the-effect-hold")
    assert "has been retracted" in tombstone.text and "material data error" in tombstone.text
    assert "Does the effect hold" not in client.get("/research").text
    assert client.get("/v1/articles").json()["articles"] == []

    rejected_bundle = publication_bundle(slug="rejected-investigation", bundle_id="bundle-rejected")
    assert client.post("/v1/admin/publications", json=rejected_bundle,
                       headers=auth("core", "service")).status_code == 201
    rejected = client.post("/v1/admin/publications/bundle-rejected/reject",
                           json={"reason": "The limitations are not adequately disclosed."},
                           headers=auth("editor", "editor"))
    assert rejected.status_code == 200 and rejected.json()["status"] == "rejected"
    assert client.post("/v1/admin/publications/bundle-rejected/publish",
                       headers=auth("editor", "editor")).status_code == 409


@pytest.mark.spec("WEB-UI-002", "WEB-UI-003")
def test_published_article_is_shareable_and_ends_in_open_questions(client):
    payload = publication_bundle()
    client.post("/v1/admin/publications", json=payload, headers=auth("core-service", "service"))
    client.post("/v1/admin/publications/bundle-1/publish", headers=auth("editor-1", "editor"))
    article = client.get("/research/does-the-effect-hold")
    canonical = "http://127.0.0.1:8080/research/does-the-effect-hold"
    html = article.text
    assert f'<link rel="canonical" href="{canonical}">' in html
    for tag in ('property="og:type" content="article"', f'property="og:url" content="{canonical}"',
                'property="og:title" content="Does the effect hold outside the original sample?"',
                'name="twitter:card" content="summary_large_image"', 'property="article:published_time"'):
        assert tag in html
    links = {network: unescape(href) for network, href in
             re.findall(r'class="share-(\w+)" href="([^"]+)"', html)}
    assert set(links) == {"linkedin", "x", "bluesky", "facebook", "reddit", "email"}
    assert parse_qs(urlsplit(links["linkedin"]).query)["url"] == [canonical]
    assert parse_qs(urlsplit(links["facebook"]).query)["u"] == [canonical]
    assert canonical in parse_qs(urlsplit(links["bluesky"]).query)["text"][0]
    x_query = parse_qs(urlsplit(links["x"]).query)
    assert x_query["url"] == [canonical] and x_query["text"][0].startswith("Does the effect hold")
    assert links["email"].startswith("mailto:?subject=") and canonical in unescape(
        parse_qs(urlsplit(links["email"]).query)["body"][0])
    assert 'class="share-copy"' in html and 'class="share-native"' in html
    assert html.count('aria-label="Share via ') == 6
    assert html.count('class="visually-hidden"') >= 8
    scripts = re.findall(r'<script[^>]*src="([^"]+)"', html)
    assert scripts and all(urlsplit(src).netloc in {"", "testserver"} and
                           urlsplit(src).path.startswith("/static/") for src in scripts)
    assert article.headers["content-security-policy"].startswith("default-src 'self'")

    findings = html.split('id="answer-panel"', 1)[1].split('id="record-panel"', 1)[0]
    assert "Questions this leaves open" in findings
    assert "Which preregistered design best distinguishes the competing explanations?" in findings
    assert "Material limitations" in findings and "non-equivalent outcome measures" in findings


@pytest.mark.spec("WEB-MOD-001", "WEB-SEC-002")
def test_review_console_is_role_gated(session_factory):
    mailer = CaptureMailer()
    settings = Settings(jwt_secret=SECRET, admin_emails=("owner@example.org",))
    with TestClient(create_app(settings=settings, session_factory=session_factory,
                               mailer=mailer)) as client:
        anonymous = client.get("/moderation")
        assert "Reviewer access required" in anonymous.text and "moderation.js" not in anonymous.text

        def sign_in(email):
            client.post("/v1/auth/magic-link", json={"email": email})
            token = parse_qs(urlsplit(mailer.deliveries[-1][1]).query)["token"][0]
            client.get(f"/auth/verify?token={token}")
            return client.get("/v1/auth/session").json()["csrf_token"]

        grant_access(client, "member@example.org")
        csrf = sign_in("member@example.org")
        assert "Reviewer access required" in client.get("/moderation").text
        assert 'href="/moderation"' not in client.get("/").text
        assert client.get("/v1/admin/submissions", headers={"X-CSRF-Token": csrf}).status_code == 403
        client.post("/v1/auth/logout", headers={"X-CSRF-Token": csrf})

        with session_factory() as session:
            from orl_web.models import Role, User
            member = session.scalar(select(User).where(User.email == "member@example.org"))
            member.role = Role.moderator
            session.commit()
        csrf = sign_in("member@example.org")
        console = client.get("/moderation").text
        assert "Questions awaiting review" in console and "Flagged questions" in console
        assert "Invitation requests" not in console and "Weekly cycle" not in console
        assert 'href="/moderation"' in client.get("/").text
        assert client.get("/v1/admin/submissions").status_code == 200
        assert client.get("/v1/admin/access-requests").status_code == 403
        assert client.get("/v1/admin/cycles").status_code == 403
        client.post("/v1/auth/logout", headers={"X-CSRF-Token": csrf})

        sign_in("owner@example.org")
        console = client.get("/moderation").text
        assert "Invitation requests" in console and "Weekly cycle" in console
        assert 'data-admin="true"' in console
        assert client.get("/v1/admin/access-requests").status_code == 200
