"""Authoritative Web domain model. No table contains Core source material."""
from __future__ import annotations

import enum
import uuid
from datetime import UTC, datetime

from sqlalchemy import (JSON, Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer,
                        String, Text, UniqueConstraint, event, text)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


def new_id() -> str:
    return str(uuid.uuid4())


class Base(DeclarativeBase):
    pass


class Role(str, enum.Enum):
    user = "user"
    paid = "paid"
    moderator = "moderator"
    editor = "editor"
    admin = "admin"
    service = "service"


class ModerationState(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    rejected = "rejected"


class PublicStatus(str, enum.Enum):
    open = "open"
    selected = "selected"
    answered = "answered"
    deferred = "deferred"
    closed = "closed"


class CycleState(str, enum.Enum):
    draft = "draft"
    open = "open"
    frozen = "frozen"


class AccessStatus(str, enum.Enum):
    pending = "pending"
    approved = "approved"
    declined = "declined"
    revoked = "revoked"


class User(Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    external_subject: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), unique=True, index=True)
    role: Mapped[Role] = mapped_column(Enum(Role, native_enum=False), nullable=False, default=Role.user)
    voting_eligible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AccessRequest(Base):
    """Invite-only membership record for one normalized email address."""
    __tablename__ = "access_requests"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    role: Mapped[str] = mapped_column(String(40), nullable=False, default="")
    discipline: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="request")
    status: Mapped[AccessStatus] = mapped_column(
        Enum(AccessStatus, native_enum=False), nullable=False, default=AccessStatus.pending, index=True)
    decision_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    decided_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow,
                                                 nullable=False, index=True)


class MagicLinkToken(Base):
    __tablename__ = "magic_link_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow,
                                                  nullable=False, index=True)


class BrowserSession(Base):
    __tablename__ = "browser_sessions"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ResearchSubscription(Base):
    __tablename__ = "research_subscriptions"
    __table_args__ = (UniqueConstraint("user_id", "kind", "value_key",
                                       name="uq_research_subscription"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    value_key: Mapped[str] = mapped_column(String(160), nullable=False)
    label: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class FeedAccessToken(Base):
    __tablename__ = "feed_access_tokens"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), unique=True,
                                         nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuestionSubmission(Base):
    __tablename__ = "question_submissions"
    __table_args__ = (UniqueConstraint("submitter_id", "idempotency_key", name="uq_submission_idempotency"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    submitter_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    original_text: Mapped[str] = mapped_column(Text, nullable=False)
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    suggested_domain: Mapped[str | None] = mapped_column(String(64))
    moderation_state: Mapped[ModerationState] = mapped_column(
        Enum(ModerationState, native_enum=False), nullable=False, default=ModerationState.pending)
    moderation_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    answer: Mapped[str] = mapped_column(Text, nullable=False, default="")
    answered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    moderated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class QuestionCluster(Base):
    __tablename__ = "question_clusters"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    canonical_question: Mapped[str] = mapped_column(Text, nullable=False)
    question_revision: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    public_status: Mapped[PublicStatus] = mapped_column(
        Enum(PublicStatus, native_enum=False), nullable=False, default=PublicStatus.open, index=True)
    tags: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    domain: Mapped[str | None] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ClusterMembership(Base):
    __tablename__ = "cluster_memberships"
    __table_args__ = (
        Index("uq_active_membership_submission", "submission_id", unique=True,
              postgresql_where=text("active"), sqlite_where=text("active = 1")),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    submission_id: Mapped[str] = mapped_column(ForeignKey("question_submissions.id"), nullable=False, index=True)
    cluster_id: Mapped[str] = mapped_column(ForeignKey("question_clusters.id"), nullable=False, index=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    decision: Mapped[str] = mapped_column(String(40), nullable=False, default="manual")
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class WeeklyCycle(Base):
    __tablename__ = "weekly_cycles"
    __table_args__ = (
        Index("uq_one_open_cycle", "state", unique=True,
              postgresql_where=text("state = 'open'"), sqlite_where=text("state = 'open'")),
    )
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    cycle_key: Mapped[str] = mapped_column(String(16), unique=True, nullable=False)
    starts_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ends_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    state: Mapped[CycleState] = mapped_column(Enum(CycleState, native_enum=False), nullable=False)
    vote_snapshot: Mapped[dict | None] = mapped_column(JSON)
    selection_reason: Mapped[str] = mapped_column(Text, nullable=False, default="")
    frozen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class CycleSelection(Base):
    """The question selected for research in one domain of a frozen weekly cycle."""
    __tablename__ = "cycle_selections"
    __table_args__ = (UniqueConstraint("cycle_id", "domain", name="uq_cycle_selection_domain"),
                      UniqueConstraint("cycle_id", "cluster_id", name="uq_cycle_selection_cluster"))
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    cycle_id: Mapped[str] = mapped_column(ForeignKey("weekly_cycles.id"), nullable=False, index=True)
    domain: Mapped[str] = mapped_column(String(64), nullable=False)
    cluster_id: Mapped[str] = mapped_column(ForeignKey("question_clusters.id"), nullable=False)
    votes: Mapped[int] = mapped_column(Integer, nullable=False)
    override: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Vote(Base):
    __tablename__ = "votes"
    __table_args__ = (UniqueConstraint("user_id", "cluster_id", "cycle_id", name="uq_vote_user_cluster_cycle"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    cluster_id: Mapped[str] = mapped_column(ForeignKey("question_clusters.id"), nullable=False, index=True)
    cycle_id: Mapped[str] = mapped_column(ForeignKey("weekly_cycles.id"), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class QuestionReport(Base):
    __tablename__ = "question_reports"
    __table_args__ = (UniqueConstraint("reporter_id", "cluster_id", name="uq_reporter_cluster"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    reporter_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    cluster_id: Mapped[str] = mapped_column(ForeignKey("question_clusters.id"), nullable=False,
                                            index=True)
    reason: Mapped[str] = mapped_column(String(40), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="open", index=True)
    resolution: Mapped[str] = mapped_column(Text, nullable=False, default="")
    resolved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ReadinessAssessment(Base):
    __tablename__ = "readiness_assessments"
    assessment_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    cluster_id: Mapped[str] = mapped_column(ForeignKey("question_clusters.id"), nullable=False, index=True)
    question_revision: Mapped[int] = mapped_column(Integer, nullable=False)
    label: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reasons: Mapped[list] = mapped_column(JSON, nullable=False)
    corpus_snapshot: Mapped[str] = mapped_column(String(80), nullable=False)
    assessed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False, default="manual")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class MetricsSnapshot(Base):
    __tablename__ = "metrics_snapshots"
    snapshot_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)
    content_sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class PublicationBundle(Base):
    __tablename__ = "publication_bundles"
    bundle_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    request_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    cluster_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    content_sha256: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    imported_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class Article(Base):
    __tablename__ = "articles"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    bundle_id: Mapped[str] = mapped_column(ForeignKey("publication_bundles.bundle_id"),
                                           unique=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(160), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class ArticleRevision(Base):
    __tablename__ = "article_revisions"
    __table_args__ = (UniqueConstraint("article_id", "revision", name="uq_article_revision"),)
    bundle_id: Mapped[str] = mapped_column(ForeignKey("publication_bundles.bundle_id"), primary_key=True)
    article_id: Mapped[str] = mapped_column(ForeignKey("articles.id"), nullable=False, index=True)
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    supersedes_bundle_id: Mapped[str | None] = mapped_column(String(128))
    correction_summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    markdown: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="draft", index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), index=True)
    review_note: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    actor_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False, index=True)
    action: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    target_type: Mapped[str] = mapped_column(String(40), nullable=False)
    target_id: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    details: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, nullable=False)


def _immutable(mapper, connection, target):
    raise ValueError(f"{type(target).__name__} records are immutable")


for _model in (MetricsSnapshot, PublicationBundle, AuditEvent):
    event.listen(_model, "before_update", _immutable)
    event.listen(_model, "before_delete", _immutable)
