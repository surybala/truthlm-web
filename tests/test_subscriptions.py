from __future__ import annotations

from urllib.parse import parse_qs, urlsplit
from xml.etree import ElementTree as ET

import pytest
from sqlalchemy import select

from conftest import auth, grant_access, publication_bundle
from orl_web.contracts import content_sha256
from orl_web.models import FeedAccessToken, QuestionCluster, ResearchSubscription


def sign_in(client, mailer):
    grant_access(client, "subscriber@example.org")
    assert client.post("/v1/auth/magic-link", json={"email": "subscriber@example.org"}).status_code == 202
    token = parse_qs(urlsplit(mailer.deliveries[-1][1]).query)["token"][0]
    assert client.get(f"/auth/verify?token={token}", follow_redirects=False).status_code == 303
    return client.get("/v1/auth/session").json()["csrf_token"]


@pytest.mark.spec("WEB-SUB-001")
def test_subscription_controls_require_login(client):
    response = client.get("/subscriptions", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/join"
    gated_login = client.get("/login?next=/subscriptions", follow_redirects=False)
    assert gated_login.status_code == 303 and gated_login.headers["location"] == "/join"
    assert client.get("/v1/subscriptions").status_code == 401


def publish(client, session_factory, *, bundle_id, slug, domain, researcher, research_domain=None):
    with session_factory() as session:
        cluster = QuestionCluster(canonical_question=f"What does the evidence show in {domain}?",
                                  tags=[domain], domain=research_domain)
        session.add(cluster)
        session.commit()
        cluster_id = cluster.id
    payload = publication_bundle(bundle_id=bundle_id, slug=slug)
    payload["cluster_id"] = cluster_id
    payload["article"]["title"] = f"Evidence from {domain.title()}"
    payload["article"]["summary"] = f"A transparent review of the {domain} evidence."
    payload["citations"][0]["authors"] = [researcher]
    payload["content_sha256"] = content_sha256(payload)
    assert client.post("/v1/admin/publications", json=payload,
                       headers=auth("core", "service")).status_code == 201
    assert client.post(f"/v1/admin/publications/{bundle_id}/publish",
                       headers=auth("editor", "editor")).status_code == 200


@pytest.mark.spec("WEB-FEED-001")
def test_public_research_feed_is_valid_cacheable_and_contains_only_public_work(
        client, session_factory):
    publish(client, session_factory, bundle_id="bundle-med", slug="medicine-evidence",
            domain="medicine", researcher="Ada Researcher")
    draft = publication_bundle(bundle_id="bundle-draft", slug="draft-research")
    assert client.post("/v1/admin/publications", json=draft,
                       headers=auth("core", "service")).status_code == 201

    response = client.get("/feeds/research.xml")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/rss+xml")
    assert response.headers["cache-control"] == "public, max-age=300"
    root = ET.fromstring(response.content)
    assert root.tag == "rss" and root.attrib["version"] == "2.0"
    items = root.findall("./channel/item")
    assert [item.findtext("title") for item in items] == ["Evidence from Medicine"]
    assert items[0].findtext("category") == "medicine"
    assert "Draft" not in response.text
    cached = client.get("/feeds/research.xml", headers={"If-None-Match": response.headers["etag"]})
    assert cached.status_code == 304 and cached.content == b""

    publish(client, session_factory, bundle_id="bundle-econ", slug="economics-evidence",
            domain="economics", researcher="Ada Researcher", research_domain="economics")
    latest = ET.fromstring(client.get("/feeds/research.xml").content).findall("./channel/item")[0]
    assert [category.text for category in latest.findall("category")] == ["Economics"]


@pytest.mark.spec("WEB-SUB-001", "WEB-SUB-002")
def test_personal_feed_matches_interests_and_supports_rotation_and_revocation(
        client, mailer, session_factory):
    publish(client, session_factory, bundle_id="bundle-med", slug="medicine-evidence",
            domain="medicine", researcher="Ada Researcher")
    publish(client, session_factory, bundle_id="bundle-physics", slug="physics-evidence",
            domain="physics", researcher="Nia Scientist")
    csrf = sign_in(client, mailer)
    headers = {"X-CSRF-Token": csrf}

    signed_in_home = client.get("/")
    assert "Join the waitlist" not in signed_in_home.text
    assert 'id="join-form"' not in signed_in_home.text

    page = client.get("/subscriptions")
    assert page.status_code == 200 and "Personal research feed" in page.text
    state = client.get("/v1/subscriptions").json()
    assert state["options"]["domains"] == ["medicine", "physics"]
    assert {"Ada Researcher", "Nia Scientist"} <= set(state["options"]["researchers"])
    assert client.post("/v1/subscriptions", json={"kind": "domain", "value": "medicine"}).status_code == 403
    added = client.post("/v1/subscriptions", json={"kind": "domain", "value": " Medicine "},
                        headers=headers)
    assert added.status_code == 201 and added.json()["value"] == "Medicine"
    replay = client.post("/v1/subscriptions", json={"kind": "domain", "value": "medicine"},
                         headers=headers)
    assert replay.json()["idempotent_replay"] is True

    generated = client.post("/v1/subscriptions/feed-token", headers=headers)
    assert generated.status_code == 201
    first_url = generated.json()["feed_url"]
    first_path = urlsplit(first_url).path
    personal = client.get(first_path)
    assert "Evidence from Medicine" in personal.text
    assert "Evidence from Physics" not in personal.text
    raw_token = first_path.removeprefix("/feeds/personal/").removesuffix(".xml")
    with session_factory() as session:
        stored = session.scalar(select(FeedAccessToken))
        assert stored.token_hash != raw_token
        subscription = session.scalar(select(ResearchSubscription).where(
            ResearchSubscription.kind == "domain"))
        assert subscription.value_key == "medicine"

    researcher = client.post("/v1/subscriptions", json={
        "kind": "researcher", "value": "Nia Scientist"}, headers=headers).json()
    assert "Evidence from Physics" in client.get(first_path).text
    assert client.delete(f"/v1/subscriptions/items/{researcher['subscription_id']}",
                         headers=headers).status_code == 204
    assert "Evidence from Physics" not in client.get(first_path).text

    rotated = client.post("/v1/subscriptions/feed-token", headers=headers).json()["feed_url"]
    assert client.get(first_path).status_code == 404
    rotated_path = urlsplit(rotated).path
    assert client.get(rotated_path).status_code == 200
    assert client.delete("/v1/subscriptions/feed-token", headers=headers).status_code == 204
    assert client.get(rotated_path).status_code == 404
