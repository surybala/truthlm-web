"""FastAPI application for TruthLM publishing, subscriptions, and the editorial loop."""
from __future__ import annotations

import logging
import re
import secrets
import unicodedata
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit
from xml.etree import ElementTree as ET

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markdown_it import MarkdownIt
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .auth import (Principal, csrf_for_session, optional_principal_dependency,
                   principal_dependency, require_roles, token_hash)
from .config import UNASSIGNED_DOMAIN, Settings
from .contracts import ContractError, validate_contract, verify_checksum
from .db import default_session_factory, session_dependency
from .delivery import EmailItem, compose_research_email, unsubscribe_url, valid_unsubscribe
from .email import Mailer, default_mailer
from .models import (AccessRequest, AccessStatus, Article, ArticleRevision, AuditEvent,
                     BrowserSession, ClusterMembership, EmailDelivery, FeedAccessToken,
                     MagicLinkToken, MetricsSnapshot, ModerationState, PublicStatus,
                     PublicationBundle, QuestionCluster, QuestionReport, QuestionSubmission,
                     ReadinessAssessment, ResearchSubscription, Role, User, utcnow)
from .presentation import bibliographic_references, research_journey, share_links
from .schemas import (AccessDecision, AccessInvite, AccessRequestCreate, DeliveryRun,
                      EditorialReason, EmailPreference, ManualReadiness, ModerationDecision,
                      MagicLinkRequest, QuestionCreate, QuestionReportCreate,
                      QuestionReportResolution, ResearchSubscriptionCreate)


def normalize_question(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip()


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _local_redirect_path(value: str, fallback: str = "/questions") -> str:
    try:
        parsed = urlsplit(value)
    except ValueError:
        return fallback
    unsafe_chars = any(ord(char) < 32 or ord(char) == 127 for char in value)
    if (not value.startswith("/") or parsed.scheme or parsed.netloc
            or "\\" in value or unsafe_chars):
        return fallback
    return value


def _user(session: Session, principal: Principal) -> User:
    if principal.user_id:
        user = session.get(User, principal.user_id)
        if user is None:
            raise HTTPException(401, "browser session user no longer exists")
        return user
    user = session.scalar(select(User).where(User.external_subject == principal.subject))
    if user is None:
        user = User(external_subject=principal.subject, role=principal.role)
        session.add(user)
        session.flush()
    elif user.role != principal.role:
        user.role = principal.role
        session.flush()
    return user


def _audit(session: Session, user: User, action: str, target_type: str,
           target_id: str, details: dict | None = None) -> None:
    session.add(AuditEvent(actor_id=user.id, action=action, target_type=target_type,
                           target_id=target_id, details=details or {}))


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def _readiness_payload(item: ReadinessAssessment) -> dict[str, Any]:
    return {
        "schema_version": "1", "assessment_id": item.assessment_id,
        "cluster_id": item.cluster_id, "question_revision": item.question_revision,
        "assessed_at": _iso(item.assessed_at), "expires_at": _iso(item.expires_at),
        "corpus_snapshot": item.corpus_snapshot, "label": item.label,
        "confidence": item.confidence, "reasons": item.reasons,
    }


_PACKAGE = Path(__file__).resolve().parent
_markdown = MarkdownIt("commonmark", {"html": False, "linkify": False, "typographer": False})
_ARTICLE_APPENDIX = re.compile(r"(?m)^##\s+(?:References|Verification warnings|Method)\s*$")


def _render_markdown(value: str) -> str:
    return _markdown.render(value)


def _render_article_markdown(value: str) -> str:
    """Hide legacy generated appendices now represented by structured reader views."""
    appendix = _ARTICLE_APPENDIX.search(value)
    return _render_markdown(value[:appendix.start()].rstrip() if appendix else value)


def _domain_label(labels: dict[str, str], key: str | None) -> str:
    if not key or key == UNASSIGNED_DOMAIN:
        return "Unassigned"
    return labels.get(key, key.replace("-", " ").title())


# Allowed access-decision transitions: action -> (states it may leave, resulting state).
_ACCESS_TRANSITIONS = {
    "approve": (frozenset({AccessStatus.pending, AccessStatus.declined, AccessStatus.revoked}),
                AccessStatus.approved),
    "decline": (frozenset({AccessStatus.pending}), AccessStatus.declined),
    "revoke": (frozenset({AccessStatus.approved}), AccessStatus.revoked),
}


def _access_payload(record: AccessRequest) -> dict[str, Any]:
    return {"request_id": record.id, "email": record.email, "name": record.name,
            "role": record.role, "discipline": record.discipline, "note": record.note,
            "source": record.source, "status": record.status.value,
            "decision_reason": record.decision_reason, "created_at": _iso(record.created_at),
            "decided_at": _iso(record.decided_at) if record.decided_at else None}


def _facet_key(value: str) -> str:
    normalized = re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip().casefold()
    if len(normalized) <= 160:
        return normalized
    return f"{normalized[:119]}:{sha256(normalized.encode('utf-8')).hexdigest()[:40]}"


def _article_facets(session: Session, article: Article,
                    labels: dict[str, str]) -> dict[str, list[str]]:
    bundle = session.get(PublicationBundle, article.bundle_id)
    if bundle is None:
        return {"domains": [], "researchers": []}
    cluster = session.get(QuestionCluster, bundle.cluster_id)
    values = [_domain_label(labels, cluster.domain)] if cluster and cluster.domain else []
    values += list(cluster.tags) if cluster else []
    unique: dict[str, str] = {}
    for value in values:
        text = str(value).strip()
        if text:
            unique.setdefault(text.casefold(), text)
    domains = sorted(unique.values(), key=str.casefold)
    researchers = sorted({str(author).strip() for citation in bundle.payload.get("citations", [])
                          for author in citation.get("authors", []) if str(author).strip()},
                         key=str.casefold)
    return {"domains": domains, "researchers": researchers}


_DELIVERY_ATTEMPTS = 3


def _subscriptions(session: Session, user_id: str) -> list[ResearchSubscription]:
    return list(session.scalars(select(ResearchSubscription).where(
        ResearchSubscription.user_id == user_id)))


def _interests(items: list[ResearchSubscription]) -> tuple[bool, set[str], set[str]]:
    """A member's interests: follows everything, normalized domain keys, researcher keys."""
    return (any(item.kind == "all" for item in items),
            {item.value_key for item in items if item.kind == "domain"},
            {item.value_key for item in items if item.kind == "researcher"})


def _matches(interests: tuple[bool, set[str], set[str]], facets: dict[str, list[str]]) -> bool:
    include_all, domains, researchers = interests
    return (include_all or bool(domains & {_facet_key(value) for value in facets["domains"]})
            or bool(researchers & {_facet_key(value) for value in facets["researchers"]}))


def _rss_response(request: Request, settings: Settings, session: Session,
                  articles: list[Article], *, title: str, description: str,
                  self_url: str) -> Response:
    ET.register_namespace("atom", "http://www.w3.org/2005/Atom")
    ET.register_namespace("dc", "http://purl.org/dc/elements/1.1/")
    rss = ET.Element("rss", {"version": "2.0"})
    channel = ET.SubElement(rss, "channel")
    ET.SubElement(channel, "title").text = title
    ET.SubElement(channel, "link").text = f"{settings.base_url}/research"
    ET.SubElement(channel, "description").text = description
    ET.SubElement(channel, "language").text = "en"
    ET.SubElement(channel, "{http://www.w3.org/2005/Atom}link", {
        "href": self_url, "rel": "self", "type": "application/rss+xml"})
    if articles:
        latest = max(article.published_at for article in articles if article.published_at)
        ET.SubElement(channel, "lastBuildDate").text = format_datetime(
            latest.replace(tzinfo=UTC) if latest.tzinfo is None else latest, usegmt=True)
    for article in articles:
        item = ET.SubElement(channel, "item")
        article_url = f"{settings.base_url}/research/{quote(article.slug)}"
        ET.SubElement(item, "title").text = article.title
        ET.SubElement(item, "link").text = article_url
        ET.SubElement(item, "guid", {"isPermaLink": "true"}).text = article_url
        ET.SubElement(item, "description").text = article.summary
        published = article.published_at.replace(tzinfo=UTC) if article.published_at.tzinfo is None \
            else article.published_at
        ET.SubElement(item, "pubDate").text = format_datetime(published, usegmt=True)
        facets = _article_facets(session, article, settings.domain_labels)
        for domain in facets["domains"]:
            ET.SubElement(item, "category").text = domain
        for researcher in facets["researchers"]:
            ET.SubElement(item, "{http://purl.org/dc/elements/1.1/}creator").text = researcher
    content = ET.tostring(rss, encoding="utf-8", xml_declaration=True)
    etag = f'"{sha256(content).hexdigest()}"'
    headers = {"Cache-Control": "public, max-age=300", "ETag": etag,
               "X-Content-Type-Options": "nosniff"}
    if request.headers.get("If-None-Match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(content=content, media_type="application/rss+xml; charset=utf-8", headers=headers)


def create_app(*, settings: Settings | None = None, session_factory=None,
               mailer: Mailer | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    settings.validate()
    factory = session_factory or default_session_factory()
    mailer = mailer or default_mailer(settings)
    get_session = session_dependency(factory)
    current = principal_dependency(settings)
    optional_current = optional_principal_dependency(settings)
    any_user = require_roles(current, *tuple(Role))
    moderator = require_roles(current, Role.moderator, Role.admin)
    editor = require_roles(current, Role.editor, Role.admin)
    admin = require_roles(current, Role.admin)
    service = require_roles(current, Role.service, Role.admin)
    publisher = require_roles(current, Role.editor, Role.admin, Role.service)
    question_author = require_roles(current, Role.editor, Role.admin)

    app = FastAPI(title="TruthLM API", version="0.1.0",
                  description="Public research publishing and email subscription service for ORL")
    app.mount("/static", StaticFiles(directory=_PACKAGE / "static"), name="static")
    templates = Jinja2Templates(directory=_PACKAGE / "templates")
    templates.env.globals.update(base_url=settings.base_url, access_mode=settings.access_mode,
                                 domain_labels=settings.domain_labels)

    def access_allowed(session: Session, email: str) -> bool:
        if email in settings.admin_emails or email in settings.editor_emails:
            return True
        record = session.scalar(select(AccessRequest).where(AccessRequest.email == email))
        if record is not None and record.status == AccessStatus.revoked:
            return False
        if settings.access_mode == "open" or (
                record is not None and record.status == AccessStatus.approved):
            return True
        user = session.scalar(select(User).where(User.email == email))
        return user is not None and user.role != Role.user

    def new_member_role(email: str) -> Role:
        if email in settings.admin_emails:
            return Role.admin
        return Role.editor if email in settings.editor_emails else Role.user

    def ensure_member(session: Session, email: str) -> User:
        """Return the member account for an address, creating a subscriber following all research."""
        user = session.scalar(select(User).where(User.email == email))
        if user is None:
            user = User(external_subject=f"email:{email}", email=email, role=new_member_role(email))
            session.add(user)
            session.flush()
            session.add(ResearchSubscription(user_id=user.id, kind="all", value_key="all",
                                             label="All weekly research"))
            session.flush()
        return user

    def decide_access(session: Session, actor: User, record: AccessRequest,
                      status: AccessStatus, reason: str) -> User | None:
        previous = record.status
        now = utcnow()
        record.status = status
        record.decision_reason = reason
        record.decided_by = actor.id
        record.decided_at = now
        if status == AccessStatus.revoked:
            member = session.scalar(select(User).where(User.email == record.email))
            if member is not None:
                session.execute(update(BrowserSession).where(
                    BrowserSession.user_id == member.id, BrowserSession.revoked_at.is_(None))
                    .values(revoked_at=now))
        _audit(session, actor, f"access.{status.value}", "access_request", record.id,
               {"reason": reason, "previous": previous.value})
        return ensure_member(session, record.email) if status == AccessStatus.approved else None

    def notify_access(record: AccessRequest, member: User) -> bool:
        try:
            mailer.send_access_approved(record.email, f"{settings.base_url}/login",
                                        unsubscribe_url(settings.base_url, member.id,
                                                        settings.jwt_secret))
        except Exception:
            logging.getLogger("orl_web.access").exception(
                "access approval notice failed for request %s", record.id)
            return False
        return True

    @app.middleware("http")
    async def browser_session(request: Request, call_next):
        request.state.principal = None
        raw_token = request.cookies.get(settings.session_cookie_name)
        if raw_token:
            with factory() as session:
                stored = session.get(BrowserSession, token_hash(raw_token))
                now = utcnow()
                if stored and stored.revoked_at is None:
                    expires = stored.expires_at.replace(tzinfo=UTC) if stored.expires_at.tzinfo is None \
                        else stored.expires_at
                    if expires > now:
                        user = session.get(User, stored.user_id)
                        if user:
                            request.state.principal = Principal(
                                subject=user.external_subject, role=user.role, user_id=user.id,
                                auth_kind="session",
                                csrf_token=csrf_for_session(raw_token, settings.jwt_secret))
        return await call_next(request)

    @app.middleware("http")
    async def browser_security_headers(request: Request, call_next):
        response = await call_next(request)
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'; "
            "img-src 'self' data:; script-src 'self' https://cdn.jsdelivr.net; "
            "style-src 'self' https://cdn.jsdelivr.net"
        )
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        return response

    @app.get("/healthz")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/login", response_class=HTMLResponse)
    def login_page(request: Request, next_path: str = Query(default="/questions", alias="next")):
        next_path = _local_redirect_path(next_path)
        if getattr(request.state, "principal", None):
            return RedirectResponse(next_path, 303)
        if settings.access_mode == "invite" and next_path == "/subscriptions":
            return RedirectResponse("/join", 303)
        return templates.TemplateResponse(request, "login.html", {
            "next_path": next_path, "magic_link_minutes": settings.magic_link_minutes})

    @app.post("/v1/auth/magic-link", status_code=202)
    def request_magic_link(body: MagicLinkRequest, session: Session = Depends(get_session)):
        neutral = {"message": "If that address has access to TruthLM, a sign-in link is on its way."}
        if not access_allowed(session, body.email):
            return neutral
        since = utcnow() - timedelta(hours=1)
        recent = session.scalar(select(func.count()).select_from(MagicLinkToken).where(
            MagicLinkToken.email == body.email, MagicLinkToken.created_at >= since)) or 0
        if recent >= settings.magic_link_limit_per_hour:
            return neutral
        raw_token = secrets.token_urlsafe(32)
        item = MagicLinkToken(token_hash=token_hash(raw_token), email=body.email,
                              expires_at=utcnow() + timedelta(minutes=settings.magic_link_minutes))
        session.add(item)
        session.flush()
        verify_url = (f"{settings.base_url}/auth/verify?token={quote(raw_token)}"
                      f"&next={quote(body.next_path)}")
        try:
            mailer.send(body.email, verify_url)
            session.commit()
        except Exception as exc:
            session.rollback()
            raise HTTPException(503, "sign-in email is temporarily unavailable") from exc
        return neutral

    @app.get("/auth/verify")
    def verify_magic_link(request: Request, token: str = Query(min_length=20, max_length=200),
                          next_path: str = Query(default="/questions", alias="next", max_length=300),
                          session: Session = Depends(get_session)):
        next_path = _local_redirect_path(next_path)
        item = session.scalar(select(MagicLinkToken).where(
            MagicLinkToken.token_hash == token_hash(token)).with_for_update())
        now = utcnow()
        invalid = item is None or item.consumed_at is not None
        if item is not None:
            expires = item.expires_at.replace(tzinfo=UTC) if item.expires_at.tzinfo is None else item.expires_at
            invalid = invalid or expires <= now
        if not invalid and not access_allowed(session, item.email):
            item.consumed_at = now
            session.commit()
            invalid = True
        if invalid:
            return templates.TemplateResponse(request, "login.html", {
                "next_path": "/questions",
                "magic_link_minutes": settings.magic_link_minutes,
                "error": "That sign-in link is invalid or has expired. Request a new one.",
            }, status_code=400)
        user = ensure_member(session, item.email)
        raw_session = secrets.token_urlsafe(32)
        stored = BrowserSession(token_hash=token_hash(raw_session), user_id=user.id,
                                expires_at=now + timedelta(days=settings.session_days))
        session.add(stored)
        item.consumed_at = now
        _audit(session, user, "auth.signed_in", "browser_session", stored.token_hash[:16])
        session.commit()
        response = RedirectResponse(next_path, status_code=303)
        response.set_cookie(settings.session_cookie_name, raw_session,
                            max_age=settings.session_days * 86400, httponly=True,
                            secure=settings.environment == "production", samesite="lax", path="/")
        return response

    @app.get("/v1/auth/session")
    def auth_session(principal: Principal | None = Depends(optional_current)) -> dict[str, Any]:
        if principal is None:
            return {"authenticated": False}
        return {"authenticated": True, "role": principal.role.value,
                "csrf_token": principal.csrf_token if principal.auth_kind == "session" else None}

    @app.post("/v1/auth/logout", status_code=204)
    def logout(request: Request, principal: Principal = Depends(any_user),
               session: Session = Depends(get_session)) -> Response:
        if principal.auth_kind != "session":
            raise HTTPException(400, "logout requires a browser session")
        raw_token = request.cookies.get(settings.session_cookie_name, "")
        stored = session.get(BrowserSession, token_hash(raw_token))
        if stored and stored.revoked_at is None:
            stored.revoked_at = utcnow()
            user = _user(session, principal)
            _audit(session, user, "auth.signed_out", "browser_session", stored.token_hash[:16])
            session.commit()
        response = Response(status_code=204)
        response.delete_cookie(settings.session_cookie_name, path="/")
        return response

    @app.get("/join", response_class=HTMLResponse)
    def join_page(request: Request):
        return templates.TemplateResponse(request, "join.html", {})

    @app.post("/v1/access-requests", status_code=202)
    def request_access(body: AccessRequestCreate,
                       session: Session = Depends(get_session)) -> dict[str, str]:
        # The global cap is checked first so a throttled response is identical for every address.
        since = utcnow() - timedelta(hours=1)
        recent = session.scalar(select(func.count()).select_from(AccessRequest).where(
            AccessRequest.source == "request", AccessRequest.created_at >= since)) or 0
        if recent >= settings.access_request_limit_per_hour:
            raise HTTPException(429, "Invitation requests are paused for a moment. Please try again later.")
        neutral = {"message": "Thank you. If we can offer you a place, we will email you."}
        if session.scalar(select(AccessRequest.id).where(AccessRequest.email == body.email)):
            return neutral
        session.add(AccessRequest(email=body.email, name=body.name, role=body.role,
                                  discipline=body.discipline, note=body.note, source="request"))
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
        return neutral

    @app.get("/v1/admin/access-requests")
    def access_requests(status: str = Query(default="pending",
                                            pattern="^(pending|approved|declined|revoked|all)$"),
                        principal: Principal = Depends(admin),
                        session: Session = Depends(get_session)) -> dict[str, Any]:
        query = select(AccessRequest).order_by(AccessRequest.created_at, AccessRequest.id).limit(500)
        if status != "all":
            query = query.where(AccessRequest.status == AccessStatus(status))
        return {"access_mode": settings.access_mode,
                "requests": [_access_payload(item) for item in session.scalars(query)]}

    @app.post("/v1/admin/access-requests/{request_id}/decision")
    def decide_access_request(request_id: str, body: AccessDecision,
                              principal: Principal = Depends(admin),
                              session: Session = Depends(get_session)) -> dict[str, Any]:
        actor = _user(session, principal)
        record = session.get(AccessRequest, request_id)
        if record is None:
            raise HTTPException(404, "access request not found")
        allowed_from, target = _ACCESS_TRANSITIONS[body.action]
        if record.status == target:
            return {**_access_payload(record), "notified": False, "idempotent_replay": True}
        if record.status not in allowed_from:
            raise HTTPException(409, f"cannot {body.action} a {record.status.value} request")
        member = decide_access(session, actor, record, target, body.reason)
        session.commit()
        notified = notify_access(record, member) if member is not None else False
        return {**_access_payload(record), "notified": notified, "idempotent_replay": False}

    @app.post("/v1/admin/access")
    def invite_member(body: AccessInvite, principal: Principal = Depends(admin),
                      session: Session = Depends(get_session)) -> dict[str, Any]:
        actor = _user(session, principal)
        record = session.scalar(select(AccessRequest).where(AccessRequest.email == body.email))
        if record is not None and record.status == AccessStatus.approved:
            return {**_access_payload(record), "notified": False, "idempotent_replay": True}
        if record is None:
            record = AccessRequest(email=body.email, name=body.name.strip(), source="invite",
                                   status=AccessStatus.pending)
            session.add(record)
            session.flush()
        member = decide_access(session, actor, record, AccessStatus.approved, body.reason)
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(409, "that address was added concurrently; reload and retry") from exc
        return {**_access_payload(record), "notified": notify_access(record, member),
                "idempotent_replay": False}

    @app.get("/subscriptions", response_class=HTMLResponse)
    def subscriptions_page(request: Request):
        if getattr(request.state, "principal", None) is None:
            destination = "/join" if settings.access_mode == "invite" else "/login?next=/subscriptions"
            return RedirectResponse(destination, status_code=303)
        return templates.TemplateResponse(request, "subscriptions.html", {
            "public_feed_url": f"{settings.base_url}/feeds/research.xml"})

    def subscription_state(session: Session, user: User) -> dict[str, Any]:
        selected = list(session.scalars(select(ResearchSubscription).where(
            ResearchSubscription.user_id == user.id).order_by(
                ResearchSubscription.kind, ResearchSubscription.label)))
        articles = list(session.scalars(select(Article).where(
            Article.status == "published").order_by(Article.published_at.desc()).limit(100)))
        domains: set[str] = set()
        researchers: set[str] = set()
        for article in articles:
            facets = _article_facets(session, article, settings.domain_labels)
            domains.update(facets["domains"])
            researchers.update(facets["researchers"])
        feed = session.scalar(select(FeedAccessToken).where(FeedAccessToken.user_id == user.id))
        return {
            "subscriptions": [{"subscription_id": item.id, "kind": item.kind,
                               "value": item.label} for item in selected],
            "options": {"domains": sorted(domains, key=str.casefold),
                        "researchers": sorted(researchers, key=str.casefold)},
            "personal_feed_active": feed is not None,
            "email_enabled": user.email_opt_out_at is None,
            "public_feed_url": f"{settings.base_url}/feeds/research.xml",
        }

    def set_email_delivery(session: Session, user: User, enabled: bool) -> None:
        if enabled == (user.email_opt_out_at is None):
            return
        now = utcnow()
        if enabled:
            user.email_opt_out_at = None
            user.email_subscribed_at = now
        else:
            user.email_opt_out_at = now
        _audit(session, user, "email.subscribed" if enabled else "email.unsubscribed",
               "email_subscription", user.id)

    @app.put("/v1/subscriptions/email")
    def update_email_delivery(body: EmailPreference, principal: Principal = Depends(any_user),
                              session: Session = Depends(get_session)) -> dict[str, bool]:
        user = _user(session, principal)
        set_email_delivery(session, user, body.enabled)
        session.commit()
        return {"email_enabled": user.email_opt_out_at is None}

    def unsubscribe_member(session: Session, user_id: str, signature: str) -> User:
        user = session.get(User, user_id) if len(signature) == 64 else None
        if user is None or not valid_unsubscribe(user_id, signature, settings.jwt_secret):
            raise HTTPException(404, "unsubscribe link not found")
        return user

    def unsubscribe_page(request: Request, user: User, *, action: str) -> HTMLResponse:
        return templates.TemplateResponse(request, "unsubscribe.html", {
            "action": action, "unsubscribed": user.email_opt_out_at is not None})

    @app.get("/unsubscribe/{user_id}/{signature}", response_class=HTMLResponse)
    def unsubscribe_confirmation(user_id: str, signature: str, request: Request,
                                 session: Session = Depends(get_session)):
        user = unsubscribe_member(session, user_id, signature)
        return unsubscribe_page(request, user, action=request.url.path)

    @app.post("/unsubscribe/{user_id}/{signature}", response_class=HTMLResponse)
    def unsubscribe(user_id: str, signature: str, request: Request,
                    session: Session = Depends(get_session)):
        """Accepts the confirmation form and RFC 8058 one-click requests from mail providers."""
        user = unsubscribe_member(session, user_id, signature)
        set_email_delivery(session, user, False)
        session.commit()
        return unsubscribe_page(request, user, action=request.url.path)

    @app.get("/v1/subscriptions")
    def list_subscriptions(principal: Principal = Depends(any_user),
                           session: Session = Depends(get_session)) -> dict[str, Any]:
        return subscription_state(session, _user(session, principal))

    @app.post("/v1/subscriptions", status_code=201)
    def add_subscription(body: ResearchSubscriptionCreate,
                         principal: Principal = Depends(any_user),
                         session: Session = Depends(get_session)) -> dict[str, Any]:
        user = _user(session, principal)
        label = "All weekly research" if body.kind == "all" else body.value
        value_key = "all" if body.kind == "all" else _facet_key(body.value)
        existing = session.scalar(select(ResearchSubscription).where(
            ResearchSubscription.user_id == user.id, ResearchSubscription.kind == body.kind,
            ResearchSubscription.value_key == value_key))
        if existing:
            return {"subscription_id": existing.id, "kind": existing.kind,
                    "value": existing.label, "idempotent_replay": True}
        item = ResearchSubscription(user_id=user.id, kind=body.kind,
                                    value_key=value_key, label=label)
        session.add(item)
        session.flush()
        _audit(session, user, "subscription.added", "research_subscription", item.id,
               {"kind": item.kind, "value": item.label})
        try:
            session.commit()
        except IntegrityError:
            session.rollback()
            replay = session.scalar(select(ResearchSubscription).where(
                ResearchSubscription.user_id == user.id,
                ResearchSubscription.kind == body.kind,
                ResearchSubscription.value_key == value_key))
            if replay is None:
                raise
            return {"subscription_id": replay.id, "kind": replay.kind,
                    "value": replay.label, "idempotent_replay": True}
        return {"subscription_id": item.id, "kind": item.kind,
                "value": item.label, "idempotent_replay": False}

    @app.delete("/v1/subscriptions/items/{subscription_id}", status_code=204)
    def remove_subscription(subscription_id: str, principal: Principal = Depends(any_user),
                            session: Session = Depends(get_session)) -> Response:
        user = _user(session, principal)
        item = session.scalar(select(ResearchSubscription).where(
            ResearchSubscription.id == subscription_id,
            ResearchSubscription.user_id == user.id))
        if item:
            details = {"kind": item.kind, "value": item.label}
            session.delete(item)
            _audit(session, user, "subscription.removed", "research_subscription",
                   subscription_id, details)
            session.commit()
        return Response(status_code=204)

    @app.post("/v1/subscriptions/feed-token", status_code=201)
    def rotate_feed_token(principal: Principal = Depends(any_user),
                          session: Session = Depends(get_session)) -> dict[str, str]:
        user = _user(session, principal)
        existing = session.scalar(select(FeedAccessToken).where(FeedAccessToken.user_id == user.id))
        if existing:
            session.delete(existing)
            session.flush()
        raw_token = secrets.token_urlsafe(32)
        stored = FeedAccessToken(token_hash=token_hash(raw_token), user_id=user.id)
        session.add(stored)
        _audit(session, user, "subscription.feed_rotated", "feed_access_token",
               stored.token_hash[:16])
        session.commit()
        return {"feed_url": f"{settings.base_url}/feeds/personal/{raw_token}.xml"}

    @app.delete("/v1/subscriptions/feed-token", status_code=204)
    def revoke_feed_token(principal: Principal = Depends(any_user),
                          session: Session = Depends(get_session)) -> Response:
        user = _user(session, principal)
        existing = session.scalar(select(FeedAccessToken).where(FeedAccessToken.user_id == user.id))
        if existing:
            target = existing.token_hash[:16]
            session.delete(existing)
            _audit(session, user, "subscription.feed_revoked", "feed_access_token", target)
            session.commit()
        return Response(status_code=204)

    @app.get("/feeds/research.xml")
    def research_feed(request: Request, session: Session = Depends(get_session)) -> Response:
        articles = list(session.scalars(select(Article).where(
            Article.status == "published").order_by(Article.published_at.desc()).limit(100)))
        return _rss_response(request, settings, session, articles, title="TruthLM Research",
                             description="Weekly evidence-led investigations with transparent methods.",
                             self_url=f"{settings.base_url}/feeds/research.xml")

    @app.get("/feeds/personal/{raw_token}.xml")
    def personal_research_feed(raw_token: str, request: Request,
                               session: Session = Depends(get_session)) -> Response:
        if not 20 <= len(raw_token) <= 200:
            raise HTTPException(404, "feed not found")
        access = session.get(FeedAccessToken, token_hash(raw_token))
        if access is None:
            raise HTTPException(404, "feed not found")
        subscriptions = _subscriptions(session, access.user_id)
        interests = _interests(subscriptions)
        include_all = interests[0]
        candidates = list(session.scalars(select(Article).where(
            Article.status == "published").order_by(Article.published_at.desc()).limit(100)))
        articles = [article for article in candidates
                    if _matches(interests, _article_facets(session, article, settings.domain_labels))]
        now = utcnow()
        last_used = access.last_used_at.replace(tzinfo=UTC) if access.last_used_at and \
            access.last_used_at.tzinfo is None else access.last_used_at
        if last_used is None or last_used < now - timedelta(days=1):
            access.last_used_at = now
            session.commit()
        labels = [item.label for item in subscriptions if item.kind != "all"]
        description = "Personal TruthLM research feed"
        if labels and not include_all:
            description += f" for {', '.join(labels[:5])}"
        self_url = f"{settings.base_url}/feeds/personal/{raw_token}.xml"
        return _rss_response(request, settings, session, articles,
                             title="Your TruthLM Research", description=description,
                             self_url=self_url)

    @app.get("/", response_class=HTMLResponse)
    def index(request: Request, session: Session = Depends(get_session)):
        articles = list(session.scalars(select(Article).where(Article.status == "published")
                        .order_by(Article.published_at.desc())))
        article_cards = [{"article": article,
                          "domains": _article_facets(
                              session, article, settings.domain_labels)["domains"]}
                         for article in articles]
        metric = session.scalar(select(MetricsSnapshot).order_by(
            MetricsSnapshot.generated_at.desc(), MetricsSnapshot.snapshot_id.desc()).limit(1))
        return templates.TemplateResponse(request, "home.html", {
            "article_cards": article_cards, "metrics": metric.payload if metric else None})

    @app.get("/research", response_class=HTMLResponse)
    def articles_page(request: Request, q: str = Query(default="", max_length=200),
                      session: Session = Depends(get_session)):
        query = select(Article).where(Article.status == "published")
        normalized = q.strip()
        if normalized:
            term = f"%{normalized}%"
            query = query.where((Article.title.ilike(term)) | (Article.summary.ilike(term)))
        articles = list(session.scalars(query.order_by(Article.published_at.desc()).limit(50)))
        return templates.TemplateResponse(request, "articles.html", {"articles": articles, "q": normalized})

    @app.get("/research/{slug}", response_class=HTMLResponse)
    def article_page(slug: str, request: Request, session: Session = Depends(get_session)):
        article = session.scalar(select(Article).where(
            Article.slug == slug, Article.status.in_(("published", "retracted"))))
        if not article:
            raise HTTPException(404, "published article not found")
        bundle = session.get(PublicationBundle, article.bundle_id)
        current_revision = session.get(ArticleRevision, article.bundle_id)
        history = list(session.scalars(select(ArticleRevision).where(
            ArticleRevision.article_id == article.id,
            ArticleRevision.status.in_(("published", "superseded", "retracted")))
            .order_by(ArticleRevision.revision.desc())))
        gates = [dict(item) for item in bundle.payload["gates"]]
        editorial = next((item for item in gates if item["name"] == "editorial_review"), None)
        if editorial:
            editorial.update(passed=True, summary="Approved by a TruthLM editor before publication.")
        record = bundle.payload["research_record"]
        references = bibliographic_references(bundle.payload["citations"])
        canonical_url = f"{settings.base_url}/research/{quote(article.slug)}"
        return templates.TemplateResponse(request, "article.html", {
            "canonical_url": canonical_url,
            "share_links": share_links(canonical_url, article.title, article.summary),
            "article": article, "article_html": _render_article_markdown(article.markdown),
            "bundle": bundle.payload, "record": record,
            "references": references, "gates": gates,
            "revision": current_revision, "history": history,
            "research_journey": research_journey(record, gates),
            "audit_event_count": len(record.get("research_log") or []),
        })

    @app.get("/method", response_class=HTMLResponse)
    def method_page(request: Request):
        return templates.TemplateResponse(request, "method.html", {})

    @app.get("/questions", response_class=HTMLResponse)
    def questions_page(request: Request, viewer: Principal | None = Depends(optional_current)):
        if viewer is None:
            return RedirectResponse("/login?next=/questions", status_code=303)
        if viewer.role not in {Role.editor, Role.admin}:
            return RedirectResponse("/subscriptions", status_code=303)
        return templates.TemplateResponse(request, "questions.html", {})

    @app.get("/moderation", response_class=HTMLResponse)
    def moderation_console(request: Request):
        viewer = getattr(request.state, "principal", None)
        authorized = viewer is not None and viewer.role in {Role.moderator, Role.admin}
        return templates.TemplateResponse(request, "moderation.html", {
            "authorized": authorized, "is_admin": authorized and viewer.role == Role.admin})

    @app.get("/editor", response_class=HTMLResponse)
    def editorial_console(request: Request):
        viewer = getattr(request.state, "principal", None)
        authorized = viewer is not None and viewer.role in {Role.editor, Role.admin}
        return templates.TemplateResponse(request, "editor.html", {"authorized": authorized})

    @app.post("/v1/questions", status_code=201)
    def submit_question(body: QuestionCreate, idempotency_key: str = Header(alias="Idempotency-Key"),
                        principal: Principal = Depends(question_author),
                        session: Session = Depends(get_session)) -> dict[str, Any]:
        if not 8 <= len(idempotency_key) <= 128:
            raise HTTPException(400, "Idempotency-Key must be 8 to 128 characters")
        if body.domain is not None and body.domain not in settings.domain_labels:
            raise HTTPException(422, "choose a research domain TruthLM currently covers")
        user = _user(session, principal)
        existing = session.scalar(select(QuestionSubmission).where(
            QuestionSubmission.submitter_id == user.id,
            QuestionSubmission.idempotency_key == idempotency_key))
        if existing:
            return {"submission_id": existing.id, "moderation_state": existing.moderation_state.value,
                    "created_at": _iso(existing.created_at), "idempotent_replay": True}
        since = utcnow() - timedelta(hours=1)
        recent = session.scalar(select(func.count()).select_from(QuestionSubmission).where(
            QuestionSubmission.submitter_id == user.id, QuestionSubmission.created_at >= since)) or 0
        if recent >= settings.question_limit_per_hour:
            raise HTTPException(429, "question submission rate limit exceeded")
        normalized = normalize_question(body.text)
        item = QuestionSubmission(submitter_id=user.id, original_text=body.text,
                                  normalized_text=normalized, idempotency_key=idempotency_key,
                                  suggested_domain=body.domain)
        session.add(item)
        try:
            session.flush()
            _audit(session, user, "question.submitted", "question_submission", item.id)
            session.commit()
        except IntegrityError:
            session.rollback()
            replay = session.scalar(select(QuestionSubmission).where(
                QuestionSubmission.submitter_id == user.id,
                QuestionSubmission.idempotency_key == idempotency_key))
            if replay is None:
                raise
            return {"submission_id": replay.id, "moderation_state": replay.moderation_state.value,
                    "created_at": _iso(replay.created_at), "idempotent_replay": True}
        return {"submission_id": item.id, "moderation_state": item.moderation_state.value,
                "created_at": _iso(item.created_at), "idempotent_replay": False}

    @app.post("/v1/admin/submissions/{submission_id}/moderate")
    def moderate_submission(submission_id: str, body: ModerationDecision,
                            principal: Principal = Depends(moderator),
                            session: Session = Depends(get_session)) -> dict[str, Any]:
        actor = _user(session, principal)
        submission = session.get(QuestionSubmission, submission_id)
        if not submission:
            raise HTTPException(404, "submission not found")
        if submission.moderation_state != ModerationState.pending:
            membership = session.scalar(select(ClusterMembership).where(
                ClusterMembership.submission_id == submission.id, ClusterMembership.active.is_(True)))
            return {"submission_id": submission.id, "state": submission.moderation_state.value,
                    "cluster_id": membership.cluster_id if membership else None, "idempotent_replay": True}
        if body.action == "reject":
            if body.cluster_id or body.canonical_question or body.domain:
                raise HTTPException(422, "rejected submissions cannot be assigned to a cluster")
            submission.moderation_state = ModerationState.rejected
            submission.moderation_reason = body.reason
            submission.moderated_at = utcnow()
            _audit(session, actor, "question.rejected", "question_submission", submission.id,
                   {"reason": body.reason})
            session.commit()
            return {"submission_id": submission.id, "state": "rejected", "cluster_id": None,
                    "idempotent_replay": False}
        if body.cluster_id:
            if body.domain:
                raise HTTPException(422, "attached submissions inherit the cluster's domain")
            cluster = session.get(QuestionCluster, body.cluster_id)
            if not cluster or cluster.public_status != PublicStatus.open:
                raise HTTPException(404, "open target cluster not found")
        else:
            domain = body.domain or submission.suggested_domain
            if domain not in settings.domain_labels:
                raise HTTPException(422, "choose a research domain from the configured list")
            canonical = normalize_question(body.canonical_question or submission.normalized_text)
            if len(canonical) < 20:
                raise HTTPException(422, "canonical question is too short")
            cluster = QuestionCluster(canonical_question=canonical, domain=domain,
                                      tags=sorted(set(tag.strip().lower() for tag in body.tags if tag.strip())))
            session.add(cluster)
            session.flush()
        membership = ClusterMembership(submission_id=submission.id, cluster_id=cluster.id,
                                       actor_id=actor.id, reason=body.reason, decision="manual")
        session.add(membership)
        submission.moderation_state = ModerationState.approved
        submission.moderation_reason = body.reason
        submission.moderated_at = utcnow()
        _audit(session, actor, "question.approved", "question_submission", submission.id,
               {"cluster_id": cluster.id, "reason": body.reason})
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(409, "submission was concurrently moderated") from exc
        return {"submission_id": submission.id, "state": "approved", "cluster_id": cluster.id,
                "idempotent_replay": False}

    @app.get("/v1/admin/submissions")
    def moderation_submissions(state: ModerationState = Query(default=ModerationState.pending),
                               principal: Principal = Depends(moderator),
                               session: Session = Depends(get_session)) -> dict[str, Any]:
        items = list(session.scalars(select(QuestionSubmission).where(
            QuestionSubmission.moderation_state == state).order_by(
                QuestionSubmission.created_at, QuestionSubmission.id).limit(200)))
        return {"submissions": [{
            "submission_id": item.id, "text": item.original_text,
            "normalized_text": item.normalized_text, "state": item.moderation_state.value,
            "suggested_domain": item.suggested_domain,
            "suggested_domain_label": _domain_label(settings.domain_labels, item.suggested_domain)
            if item.suggested_domain else None,
            "reason": item.moderation_reason, "created_at": _iso(item.created_at),
        } for item in items]}

    @app.get("/v1/questions")
    def list_questions(principal: Principal = Depends(any_user),
                       session: Session = Depends(get_session)) -> dict[str, Any]:
        clusters = list(session.scalars(select(QuestionCluster).where(
            QuestionCluster.public_status.in_([PublicStatus.open, PublicStatus.selected]))
            .order_by(QuestionCluster.created_at, QuestionCluster.id)))
        items = []
        for cluster in clusters:
            readiness = session.scalar(select(ReadinessAssessment).where(
                ReadinessAssessment.cluster_id == cluster.id,
                ReadinessAssessment.question_revision == cluster.question_revision)
                .order_by(ReadinessAssessment.assessed_at.desc()).limit(1))
            domain = cluster.domain or UNASSIGNED_DOMAIN
            items.append({"cluster_id": cluster.id, "question": cluster.canonical_question,
                          "question_revision": cluster.question_revision,
                          "status": cluster.public_status.value, "tags": cluster.tags,
                          "domain": domain,
                          "domain_label": _domain_label(settings.domain_labels, domain),
                          "readiness": _readiness_payload(readiness) if readiness else None})
        # Grouped by domain in configured order; oldest first within a domain (stable sort).
        order = {key: index for index, key in enumerate(settings.domain_labels)}
        items.sort(key=lambda item: (order.get(item["domain"], len(order)), item["domain"]))
        domains = [{"key": key, "label": label} for key, label in settings.domain_labels.items()]
        if any(item["domain"] == UNASSIGNED_DOMAIN for item in items):
            domains.append({"key": UNASSIGNED_DOMAIN, "label": "Unassigned"})
        return {"domains": domains, "questions": items}

    @app.get("/v1/me/submissions")
    def my_submissions(principal: Principal = Depends(any_user),
                       session: Session = Depends(get_session)) -> dict[str, Any]:
        user = _user(session, principal)
        submissions = list(session.scalars(select(QuestionSubmission).where(
            QuestionSubmission.submitter_id == user.id).order_by(
                QuestionSubmission.created_at.desc()).limit(100)))
        memberships = {membership.submission_id: membership.cluster_id for membership in session.scalars(
            select(ClusterMembership).where(
                ClusterMembership.submission_id.in_([item.id for item in submissions]),
                ClusterMembership.active.is_(True)))} if submissions else {}
        return {"submissions": [{
            "submission_id": item.id, "text": item.original_text,
            "moderation_state": item.moderation_state.value,
            "moderation_reason": item.moderation_reason if item.moderation_state != ModerationState.pending else "",
            "cluster_id": memberships.get(item.id), "created_at": _iso(item.created_at),
        } for item in submissions]}

    @app.post("/v1/questions/{cluster_id}/report", status_code=201)
    def report_question(cluster_id: str, body: QuestionReportCreate,
                        principal: Principal = Depends(any_user),
                        session: Session = Depends(get_session)) -> dict[str, Any]:
        user = _user(session, principal)
        cluster = session.get(QuestionCluster, cluster_id)
        if not cluster:
            raise HTTPException(404, "question cluster not found")
        existing = session.scalar(select(QuestionReport).where(
            QuestionReport.reporter_id == user.id, QuestionReport.cluster_id == cluster_id))
        if existing:
            return {"report_id": existing.id, "status": existing.status, "idempotent_replay": True}
        since = utcnow() - timedelta(hours=1)
        recent = session.scalar(select(func.count()).select_from(QuestionReport).where(
            QuestionReport.reporter_id == user.id, QuestionReport.created_at >= since)) or 0
        if recent >= settings.report_limit_per_hour:
            raise HTTPException(429, "question report rate limit exceeded")
        report = QuestionReport(reporter_id=user.id, cluster_id=cluster_id,
                                reason=body.reason, details=body.details.strip())
        session.add(report)
        session.flush()
        _audit(session, user, "question.reported", "question_cluster", cluster_id,
               {"report_id": report.id, "reason": report.reason})
        session.commit()
        return {"report_id": report.id, "status": report.status, "idempotent_replay": False}

    @app.get("/v1/admin/question-reports")
    def moderation_reports(status: str = Query(default="open", pattern="^(open|resolved|dismissed)$"),
                           principal: Principal = Depends(moderator),
                           session: Session = Depends(get_session)) -> dict[str, Any]:
        rows = session.execute(select(QuestionReport, QuestionCluster).join(
            QuestionCluster, QuestionCluster.id == QuestionReport.cluster_id).where(
                QuestionReport.status == status).order_by(
                    QuestionReport.created_at, QuestionReport.id).limit(200))
        return {"reports": [{
            "report_id": report.id, "cluster_id": report.cluster_id,
            "question": cluster.canonical_question, "reason": report.reason,
            "details": report.details, "status": report.status,
            "resolution": report.resolution, "created_at": _iso(report.created_at),
            "resolved_at": _iso(report.resolved_at) if report.resolved_at else None,
        } for report, cluster in rows]}

    @app.post("/v1/admin/question-reports/{report_id}/resolve")
    def resolve_question_report(report_id: str, body: QuestionReportResolution,
                                principal: Principal = Depends(moderator),
                                session: Session = Depends(get_session)) -> dict[str, Any]:
        actor = _user(session, principal)
        report = session.get(QuestionReport, report_id)
        if not report:
            raise HTTPException(404, "question report not found")
        if report.status != "open":
            return {"report_id": report.id, "status": report.status,
                    "resolution": report.resolution, "idempotent_replay": True}
        report.status = body.status
        report.resolution = body.reason.strip()
        report.resolved_by = actor.id
        report.resolved_at = utcnow()
        _audit(session, actor, f"question.report_{body.status}", "question_report", report.id,
               {"cluster_id": report.cluster_id, "reason": report.resolution})
        session.commit()
        return {"report_id": report.id, "status": report.status,
                "resolution": report.resolution, "idempotent_replay": False}

    @app.post("/v1/admin/readiness", status_code=201)
    def record_readiness(body: ManualReadiness, principal: Principal = Depends(editor),
                         session: Session = Depends(get_session)) -> dict[str, Any]:
        actor = _user(session, principal)
        cluster = session.get(QuestionCluster, body.cluster_id)
        if not cluster:
            raise HTTPException(404, "cluster not found")
        if body.expires_at <= body.assessed_at:
            raise HTTPException(422, "expires_at must be after assessed_at")
        payload = {"schema_version": "1", "assessment_id": body.assessment_id,
                   "cluster_id": cluster.id, "question_revision": cluster.question_revision,
                   "assessed_at": _iso(body.assessed_at), "expires_at": _iso(body.expires_at),
                   "corpus_snapshot": body.corpus_snapshot, "label": body.label,
                   "confidence": body.confidence, "reasons": body.reasons}
        try:
            validate_contract("readiness-assessment", payload)
        except ContractError as exc:
            raise HTTPException(422, str(exc)) from exc
        existing = session.get(ReadinessAssessment, body.assessment_id)
        if existing:
            if _readiness_payload(existing) != payload:
                raise HTTPException(409, "assessment_id already exists with different content")
            return payload
        item = ReadinessAssessment(assessment_id=body.assessment_id, cluster_id=cluster.id,
                                   question_revision=cluster.question_revision, label=body.label,
                                   confidence=body.confidence, reasons=body.reasons,
                                   corpus_snapshot=body.corpus_snapshot,
                                   assessed_at=body.assessed_at, expires_at=body.expires_at,
                                   source="manual")
        session.add(item)
        _audit(session, actor, "readiness.recorded", "question_cluster", cluster.id,
               {"assessment_id": item.assessment_id, "label": item.label})
        session.commit()
        return payload

    @app.post("/v1/admin/metrics", status_code=201)
    def import_metrics(payload: dict = Body(...), principal: Principal = Depends(service),
                       session: Session = Depends(get_session)) -> dict[str, Any]:
        actor = _user(session, principal)
        try:
            validate_contract("metrics-snapshot", payload)
        except ContractError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not verify_checksum(payload):
            raise HTTPException(422, "metrics snapshot checksum mismatch")
        existing = session.get(MetricsSnapshot, payload["snapshot_id"])
        if existing:
            if existing.content_sha256 != payload["content_sha256"]:
                raise HTTPException(409, "snapshot_id already exists with different content")
            return existing.payload
        item = MetricsSnapshot(snapshot_id=payload["snapshot_id"],
                               generated_at=_parse_time(payload["generated_at"]),
                               content_sha256=payload["content_sha256"], payload=payload)
        session.add(item)
        _audit(session, actor, "metrics.imported", "metrics_snapshot", item.snapshot_id,
               {"content_sha256": item.content_sha256})
        try:
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(409, "metrics snapshot content already imported") from exc
        return payload

    @app.get("/v1/metrics/latest")
    def latest_metrics(session: Session = Depends(get_session)) -> dict[str, Any]:
        item = session.scalar(select(MetricsSnapshot).order_by(
            MetricsSnapshot.generated_at.desc(), MetricsSnapshot.snapshot_id.desc()).limit(1))
        if not item:
            raise HTTPException(404, "no metrics snapshot available")
        return item.payload

    def _editorial_item(revision: ArticleRevision, article: Article,
                        bundle: PublicationBundle | None = None) -> dict[str, Any]:
        value = {"bundle_id": revision.bundle_id, "article_id": article.id,
                 "slug": article.slug, "title": revision.title, "summary": revision.summary,
                 "revision": revision.revision, "status": revision.status,
                 "correction_summary": revision.correction_summary,
                 "review_note": revision.review_note, "created_at": _iso(revision.created_at),
                 "published_at": _iso(revision.published_at) if revision.published_at else None}
        if bundle:
            value.update(gates=bundle.payload["gates"], research_record=bundle.payload["research_record"],
                         citations=bundle.payload["citations"], markdown=revision.markdown)
        return value

    @app.get("/v1/admin/publications")
    def editorial_publications(principal: Principal = Depends(editor),
                               session: Session = Depends(get_session)) -> dict[str, Any]:
        rows = session.execute(select(ArticleRevision, Article).join(
            Article, Article.id == ArticleRevision.article_id).order_by(
                ArticleRevision.created_at.desc()).limit(200))
        return {"publications": [_editorial_item(revision, article)
                                 for revision, article in rows]}

    @app.get("/v1/admin/publications/{bundle_id}")
    def editorial_publication(bundle_id: str, principal: Principal = Depends(editor),
                              session: Session = Depends(get_session)) -> dict[str, Any]:
        revision = session.get(ArticleRevision, bundle_id)
        bundle = session.get(PublicationBundle, bundle_id)
        if not revision or not bundle:
            raise HTTPException(404, "publication bundle not found")
        article = session.get(Article, revision.article_id)
        return _editorial_item(revision, article, bundle)

    @app.post("/v1/admin/publications", status_code=201)
    def import_publication(payload: dict = Body(...), principal: Principal = Depends(publisher),
                           session: Session = Depends(get_session)) -> dict[str, Any]:
        actor = _user(session, principal)
        try:
            validate_contract("publication-bundle", payload)
        except ContractError as exc:
            raise HTTPException(422, str(exc)) from exc
        if not verify_checksum(payload):
            raise HTTPException(422, "publication bundle checksum mismatch")
        existing = session.get(PublicationBundle, payload["bundle_id"])
        if existing:
            if existing.content_sha256 != payload["content_sha256"]:
                raise HTTPException(409, "bundle_id already exists with different content")
            revision = session.get(ArticleRevision, existing.bundle_id)
            article = session.get(Article, revision.article_id)
            return {"bundle_id": existing.bundle_id, "article_id": article.id,
                    "slug": article.slug, "revision": revision.revision,
                    "status": revision.status, "idempotent_replay": True}
        gates = {gate["name"]: gate for gate in payload["gates"]}
        required_gates = {"research_review", "citation_support", "originality", "copyright",
                          "equation_validation", "quantitative_validation"}
        failed = sorted(name for name in required_gates if not gates.get(name, {}).get("passed"))
        if failed:
            raise HTTPException(422, f"publication gates not passed: {', '.join(failed)}")
        gate_names = [gate["name"] for gate in payload["gates"]]
        if len(gate_names) != len(set(gate_names)):
            raise HTTPException(422, "publication gate names must be unique")
        citation_id_list = [citation["citation_id"] for citation in payload["citations"]]
        if len(citation_id_list) != len(set(citation_id_list)):
            raise HTTPException(422, "citation IDs must be unique")
        unsafe_urls = [citation["citation_id"] for citation in payload["citations"]
                       if citation.get("url") and urlsplit(citation["url"]).scheme not in {"http", "https"}]
        if unsafe_urls:
            raise HTTPException(422, f"citation URLs must use http or https: {', '.join(unsafe_urls)}")
        citation_ids = set(citation_id_list)
        record = payload["research_record"]
        referenced = set()
        for entry in record["research_log"]:
            referenced.update(entry["evidence_refs"])
        for entry in record.get("research_journey") or []:
            referenced.update(entry["evidence_refs"])
        for claim in record["evidence_map"]:
            referenced.update(claim["supporting_citations"])
            referenced.update(claim["contradicting_citations"])
        unknown = sorted(referenced - citation_ids)
        if unknown:
            raise HTTPException(422, f"research record references unknown citations: {', '.join(unknown)}")
        article_payload = payload["article"]
        article = session.scalar(select(Article).where(Article.slug == article_payload["slug"]))
        if article is None:
            if payload["revision"] != 1 or payload["supersedes_bundle_id"] is not None:
                raise HTTPException(409, "a new article must begin at revision 1")
        else:
            latest = session.scalar(select(ArticleRevision).where(
                ArticleRevision.article_id == article.id).order_by(
                    ArticleRevision.revision.desc()).limit(1))
            if latest.status == "draft":
                raise HTTPException(409, "article already has a draft revision")
            if payload["revision"] != latest.revision + 1:
                raise HTTPException(409, f"next article revision must be {latest.revision + 1}")
            if payload["supersedes_bundle_id"] != latest.bundle_id:
                raise HTTPException(409, "revision must identify the bundle it supersedes")
            if not payload["correction_summary"].strip():
                raise HTTPException(422, "a correction summary is required after revision 1")
            if article.status == "retracted":
                raise HTTPException(409, "retracted articles cannot receive new revisions")
        bundle = PublicationBundle(bundle_id=payload["bundle_id"], request_id=payload["request_id"],
                                   cluster_id=payload["cluster_id"],
                                   content_sha256=payload["content_sha256"], payload=payload)
        session.add(bundle)
        try:
            if article is None:
                article = Article(bundle_id=bundle.bundle_id, slug=article_payload["slug"],
                                  title=article_payload["title"], summary=article_payload["summary"],
                                  markdown=article_payload["markdown"], status="draft")
                session.add(article)
                session.flush()
            revision = ArticleRevision(
                bundle_id=bundle.bundle_id, article_id=article.id, revision=payload["revision"],
                supersedes_bundle_id=payload["supersedes_bundle_id"],
                correction_summary=payload["correction_summary"], title=article_payload["title"],
                summary=article_payload["summary"], markdown=article_payload["markdown"], status="draft")
            session.add(revision)
            session.flush()
            _audit(session, actor, "publication.imported", "publication_bundle", bundle.bundle_id,
                   {"article_id": article.id, "slug": article.slug, "revision": revision.revision})
            session.commit()
        except IntegrityError as exc:
            session.rollback()
            raise HTTPException(409, "publication bundle content already imported") from exc
        return {"bundle_id": bundle.bundle_id, "article_id": article.id, "slug": article.slug,
                "revision": revision.revision, "status": revision.status, "idempotent_replay": False}

    @app.post("/v1/admin/publications/{bundle_id}/publish")
    def publish_article(bundle_id: str, principal: Principal = Depends(editor),
                        session: Session = Depends(get_session)) -> dict[str, Any]:
        actor = _user(session, principal)
        bundle = session.get(PublicationBundle, bundle_id)
        revision = session.get(ArticleRevision, bundle_id)
        if not bundle or not revision:
            raise HTTPException(404, "publication bundle not found")
        article = session.get(Article, revision.article_id)
        if revision.status == "published" and article.bundle_id == bundle_id:
            return {"bundle_id": bundle_id, "slug": article.slug, "status": "published",
                    "published_at": _iso(article.published_at), "idempotent_replay": True}
        if revision.status != "draft":
            raise HTTPException(409, f"cannot publish a {revision.status} revision")
        previous = session.scalar(select(ArticleRevision).where(
            ArticleRevision.article_id == article.id, ArticleRevision.status == "published"))
        if previous:
            previous.status = "superseded"
        published_at = utcnow()
        revision.status = "published"
        revision.published_at = published_at
        article.bundle_id = bundle_id
        article.title = revision.title
        article.summary = revision.summary
        article.markdown = revision.markdown
        article.status = "published"
        article.published_at = published_at
        _audit(session, actor, "publication.published", "article", article.id,
               {"bundle_id": bundle_id, "slug": article.slug, "revision": revision.revision})
        session.commit()
        return {"bundle_id": bundle_id, "slug": article.slug, "status": "published",
                "published_at": _iso(article.published_at), "idempotent_replay": False}

    @app.post("/v1/admin/publications/{bundle_id}/reject")
    def reject_article(bundle_id: str, body: EditorialReason, principal: Principal = Depends(editor),
                       session: Session = Depends(get_session)) -> dict[str, Any]:
        actor = _user(session, principal)
        revision = session.get(ArticleRevision, bundle_id)
        if not revision:
            raise HTTPException(404, "publication bundle not found")
        if revision.status == "rejected":
            return {"bundle_id": bundle_id, "status": "rejected", "idempotent_replay": True}
        if revision.status != "draft":
            raise HTTPException(409, f"cannot reject a {revision.status} revision")
        revision.status = "rejected"
        revision.review_note = body.reason
        article = session.get(Article, revision.article_id)
        if article.bundle_id == bundle_id and article.status == "draft":
            article.status = "rejected"
        _audit(session, actor, "publication.rejected", "article", article.id,
               {"bundle_id": bundle_id, "revision": revision.revision, "reason": body.reason})
        session.commit()
        return {"bundle_id": bundle_id, "status": "rejected", "idempotent_replay": False}

    @app.post("/v1/admin/publications/{bundle_id}/retract")
    def retract_article(bundle_id: str, body: EditorialReason, principal: Principal = Depends(editor),
                        session: Session = Depends(get_session)) -> dict[str, Any]:
        actor = _user(session, principal)
        revision = session.get(ArticleRevision, bundle_id)
        if not revision:
            raise HTTPException(404, "publication bundle not found")
        article = session.get(Article, revision.article_id)
        if revision.status == "retracted":
            return {"bundle_id": bundle_id, "status": "retracted", "idempotent_replay": True}
        if revision.status != "published" or article.bundle_id != bundle_id:
            raise HTTPException(409, "only the current published revision can be retracted")
        revision.status = "retracted"
        revision.review_note = body.reason
        article.status = "retracted"
        _audit(session, actor, "publication.retracted", "article", article.id,
               {"bundle_id": bundle_id, "revision": revision.revision, "reason": body.reason})
        session.commit()
        return {"bundle_id": bundle_id, "slug": article.slug,
                "status": "retracted", "idempotent_replay": False}

    def email_eligible(session: Session, user: User) -> bool:
        return bool(user.email) and user.email_opt_out_at is None and access_allowed(session, user.email)

    def deliverable():
        return (EmailDelivery.status == "pending") | (
            (EmailDelivery.status == "failed") & (EmailDelivery.attempts < _DELIVERY_ATTEMPTS))

    def remaining_subscribers(session: Session) -> int:
        return session.scalar(select(func.count(func.distinct(EmailDelivery.user_id)))
                              .where(deliverable())) or 0

    def queue_deliveries(session: Session) -> int:
        # Approved addresses are subscribers even if they were approved before accounts were
        # created at approval time.
        for email in list(session.scalars(select(AccessRequest.email).where(
                AccessRequest.status == AccessStatus.approved))):
            ensure_member(session, email)
        articles = list(session.scalars(select(Article).where(Article.status == "published")))
        first_published = {article_id: _aware(value) for article_id, value in session.execute(
            select(ArticleRevision.article_id, func.min(ArticleRevision.published_at))
            .where(ArticleRevision.published_at.is_not(None)).group_by(ArticleRevision.article_id))}
        facets = {article.id: _article_facets(session, article, settings.domain_labels)
                  for article in articles}
        existing = {(user_id, article_id) for user_id, article_id in session.execute(
            select(EmailDelivery.user_id, EmailDelivery.article_id))}
        queued = 0
        for user in session.scalars(select(User).where(User.email.is_not(None))
                                    .order_by(User.created_at, User.id)).all():
            if not email_eligible(session, user):
                continue
            since = _aware(user.email_subscribed_at or user.created_at)
            interests = _interests(_subscriptions(session, user.id))
            for article in articles:
                if ((user.id, article.id) not in existing and first_published[article.id] >= since
                        and _matches(interests, facets[article.id])):
                    session.add(EmailDelivery(user_id=user.id, article_id=article.id))
                    queued += 1
        session.flush()
        return queued

    def send_deliveries(session: Session, limit: int) -> tuple[int, int, int]:
        recipients = session.execute(
            select(EmailDelivery.user_id).join(User, User.id == EmailDelivery.user_id)
            .where(deliverable()).group_by(EmailDelivery.user_id, User.created_at)
            .order_by(func.min(EmailDelivery.attempts), User.created_at, EmailDelivery.user_id)
            .limit(limit)).scalars().all()
        sent = failed = skipped = 0
        for user_id in recipients:
            user = session.get(User, user_id)
            eligible = email_eligible(session, user)
            ready = []
            for item in session.scalars(select(EmailDelivery).where(
                    EmailDelivery.user_id == user_id, deliverable())
                    .order_by(EmailDelivery.created_at, EmailDelivery.id)).all():
                article = session.get(Article, item.article_id)
                if eligible and article.status == "published":
                    ready.append((item, article))
                else:
                    item.status = "skipped"
                    skipped += 1
            # Rows are claimed with a conditional update and committed before sending: a concurrent
            # run cannot claim them too, and an interrupted send stays "sending" and is never
            # emailed a second time.
            claimed = set()
            if ready:
                claimed = set(session.scalars(
                    update(EmailDelivery).where(EmailDelivery.id.in_([item.id for item, _ in ready]),
                                                deliverable())
                    .values(status="sending", attempts=EmailDelivery.attempts + 1)
                    .returning(EmailDelivery.id)))
            session.commit()
            ready = [(item, article) for item, article in ready if item.id in claimed]
            if not ready:
                continue
            message = compose_research_email([
                EmailItem(title=article.title, summary=article.summary,
                          url=f"{settings.base_url}/research/{quote(article.slug)}",
                          domains=tuple(_article_facets(session, article,
                                                        settings.domain_labels)["domains"]))
                for _, article in ready],
                base_url=settings.base_url,
                unsubscribe=unsubscribe_url(settings.base_url, user.id, settings.jwt_secret))
            try:
                mailer.send_research(user.email, message)
            except Exception as exc:
                logging.getLogger("orl_web.delivery").exception(
                    "research email failed for subscriber %s", user.id)
                for item, _ in ready:
                    item.status = "failed"
                    item.last_error = f"{type(exc).__name__}: {exc}"[:500]
                failed += 1
            else:
                now = utcnow()
                for item, _ in ready:
                    item.status = "sent"
                    item.sent_at = now
                sent += 1
            session.commit()
        return sent, failed, skipped

    @app.post("/v1/admin/deliveries/run")
    def run_delivery(body: DeliveryRun | None = None, principal: Principal = Depends(publisher),
                     session: Session = Depends(get_session)) -> dict[str, int]:
        actor = _user(session, principal)
        limit = body.limit if body and body.limit else settings.delivery_batch_size
        queued = queue_deliveries(session)
        session.commit()
        sent, failed, skipped = send_deliveries(session, limit)
        result = {"queued": queued, "emails_sent": sent, "emails_failed": failed,
                  "skipped": skipped, "remaining": remaining_subscribers(session)}
        _audit(session, actor, "delivery.run", "email_delivery", _iso(utcnow()), result)
        session.commit()
        return result

    @app.get("/v1/admin/deliveries")
    def delivery_status(principal: Principal = Depends(publisher),
                        session: Session = Depends(get_session)) -> dict[str, Any]:
        counts = dict(session.execute(select(EmailDelivery.status, func.count())
                                      .group_by(EmailDelivery.status)).all())
        members = session.scalars(select(User).where(User.email.is_not(None))).all()
        last_sent = session.scalar(select(func.max(EmailDelivery.sent_at)))
        return {"subscribers": sum(1 for user in members if email_eligible(session, user)),
                "deliveries": {status: int(counts.get(status, 0))
                               for status in ("pending", "sending", "sent", "failed", "skipped")},
                "remaining": remaining_subscribers(session),
                "last_sent_at": _iso(last_sent) if last_sent else None}

    @app.get("/v1/articles")
    def public_articles(session: Session = Depends(get_session)) -> dict[str, Any]:
        articles = list(session.scalars(select(Article).where(Article.status == "published")
                        .order_by(Article.published_at.desc()).limit(100)))
        return {"articles": [{"slug": article.slug, "title": article.title,
                              "summary": article.summary, "published_at": _iso(article.published_at)}
                             for article in articles]}

    return app


app = create_app()


def run() -> None:
    import uvicorn
    uvicorn.run("orl_web.app:app", host="127.0.0.1", port=8080)
