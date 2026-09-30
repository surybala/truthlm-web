"""HTTP request and response shapes."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


ACCESS_ROLES = frozenset({"", "student", "researcher", "educator", "practitioner", "other"})


def normalize_email(value: str) -> str:
    normalized = value.strip().lower()
    if normalized.count("@") != 1 or "." not in normalized.rsplit("@", 1)[1]:
        raise ValueError("enter a valid email address")
    return normalized


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuestionCreate(StrictModel):
    text: str = Field(min_length=20, max_length=2000)
    domain: str | None = Field(default=None, max_length=64)

    @field_validator("text")
    @classmethod
    def meaningful(cls, value: str) -> str:
        if len(value.split()) < 4:
            raise ValueError("question must contain at least four words")
        return value


class ModerationDecision(StrictModel):
    action: str
    reason: str = Field(min_length=3, max_length=1000)
    cluster_id: str | None = None
    canonical_question: str | None = Field(default=None, min_length=20, max_length=2000)
    tags: list[str] = Field(default_factory=list, max_length=20)
    domain: str | None = Field(default=None, max_length=64)

    @field_validator("action")
    @classmethod
    def action_allowed(cls, value: str) -> str:
        if value not in {"approve", "reject"}:
            raise ValueError("action must be approve or reject")
        return value


class CycleCreate(StrictModel):
    cycle_key: str = Field(pattern=r"^[0-9]{4}-W[0-9]{2}$")
    starts_at: datetime
    ends_at: datetime


class FreezeRequest(StrictModel):
    reason: str = Field(min_length=3, max_length=1000)
    override_cluster_ids: list[str] = Field(default_factory=list, max_length=50)


class ManualReadiness(StrictModel):
    assessment_id: str = Field(min_length=1, max_length=128)
    cluster_id: str
    label: str
    confidence: float = Field(ge=0, le=1)
    reasons: list[dict] = Field(min_length=1, max_length=20)
    corpus_snapshot: str = Field(pattern=r"^sha256:[a-f0-9]{64}$")
    assessed_at: datetime
    expires_at: datetime


class EditorialReason(StrictModel):
    reason: str = Field(min_length=3, max_length=2000)


class PrivateAnswer(StrictModel):
    answer: str = Field(min_length=20, max_length=100000)


class MagicLinkRequest(StrictModel):
    email: str = Field(min_length=3, max_length=320)
    next_path: str = Field(default="/questions", alias="next", max_length=300)

    @field_validator("email")
    @classmethod
    def plausible_email(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("next_path")
    @classmethod
    def local_redirect(cls, value: str) -> str:
        if not value.startswith("/") or value.startswith("//"):
            raise ValueError("next must be a local path")
        return value


class QuestionReportCreate(StrictModel):
    reason: str
    details: str = Field(default="", max_length=1000)

    @field_validator("reason")
    @classmethod
    def reason_allowed(cls, value: str) -> str:
        if value not in {"spam", "abuse", "privacy", "misleading", "other"}:
            raise ValueError("unsupported report reason")
        return value


class QuestionReportResolution(StrictModel):
    status: str
    reason: str = Field(min_length=3, max_length=1000)

    @field_validator("status")
    @classmethod
    def status_allowed(cls, value: str) -> str:
        if value not in {"resolved", "dismissed"}:
            raise ValueError("status must be resolved or dismissed")
        return value


class ResearchSubscriptionCreate(StrictModel):
    kind: str
    value: str = Field(min_length=1, max_length=160)

    @field_validator("kind")
    @classmethod
    def kind_allowed(cls, value: str) -> str:
        if value not in {"all", "domain", "researcher"}:
            raise ValueError("kind must be all, domain, or researcher")
        return value

    @field_validator("value")
    @classmethod
    def normalized_value(cls, value: str) -> str:
        normalized = " ".join(value.split())
        if not normalized:
            raise ValueError("subscription value cannot be blank")
        return normalized


class AccessRequestCreate(StrictModel):
    email: str = Field(min_length=3, max_length=320)
    name: str = Field(min_length=1, max_length=200)
    role: str = Field(default="", max_length=40)
    discipline: str = Field(default="", max_length=200)
    note: str = Field(default="", max_length=1000)

    @field_validator("email")
    @classmethod
    def plausible_email(cls, value: str) -> str:
        return normalize_email(value)

    @field_validator("name", "discipline", "note")
    @classmethod
    def trimmed(cls, value: str) -> str:
        return value.strip()

    @field_validator("name")
    @classmethod
    def named(cls, value: str) -> str:
        if not value:
            raise ValueError("enter your name")
        return value

    @field_validator("role")
    @classmethod
    def role_allowed(cls, value: str) -> str:
        if value not in ACCESS_ROLES:
            raise ValueError("unsupported role")
        return value


class AccessDecision(StrictModel):
    action: str
    reason: str = Field(min_length=3, max_length=1000)

    @field_validator("action")
    @classmethod
    def action_allowed(cls, value: str) -> str:
        if value not in {"approve", "decline", "revoke"}:
            raise ValueError("action must be approve, decline, or revoke")
        return value


class AccessInvite(StrictModel):
    email: str = Field(min_length=3, max_length=320)
    name: str = Field(default="", max_length=200)
    reason: str = Field(min_length=3, max_length=1000)

    @field_validator("email")
    @classmethod
    def plausible_email(cls, value: str) -> str:
        return normalize_email(value)
