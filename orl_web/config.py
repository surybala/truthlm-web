"""Environment-backed service configuration."""
from __future__ import annotations

import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


_DEV_SECRET = "development-only-secret-change-me"
_DEFAULT_DOMAINS = ("Biology", "Chemistry", "Economics", "Finance", "Mathematics", "Physics",
                    "Statistics")
ACCESS_MODES = frozenset({"invite", "open"})
UNASSIGNED_DOMAIN = "unassigned"
# orl-web/.env for a source checkout; an installed package (the container image) has none.
PROJECT_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


def load_env_file() -> None:
    """Load the project .env for local runs. Variables already in the environment always win;
    ORL_WEB_DOTENV=0 disables loading (the test suite sets it)."""
    if os.environ.get("ORL_WEB_DOTENV", "1") != "0":
        load_dotenv(PROJECT_ENV_FILE, override=False)


def domain_key(label: str) -> str:
    folded = unicodedata.normalize("NFKC", label).casefold()
    return re.sub(r"[^a-z0-9]+", "-", folded).strip("-")


@dataclass(frozen=True)
class Settings:
    environment: str = "development"
    database_url: str = "sqlite:///./orl-web.db"
    jwt_secret: str = _DEV_SECRET
    jwt_issuer: str = "orl-auth"
    jwt_audience: str = "orl-web"
    question_limit_per_hour: int = 5
    report_limit_per_hour: int = 10
    magic_link_limit_per_hour: int = 5
    access_request_limit_per_hour: int = 60
    delivery_batch_size: int = 50
    access_mode: str = "invite"
    domains: tuple[str, ...] = _DEFAULT_DOMAINS
    base_url: str = "http://127.0.0.1:8080"
    session_cookie_name: str = "truthlm_session"
    session_days: int = 30
    magic_link_minutes: int = 15
    email_delivery: str = "console"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = ""
    smtp_starttls: bool = True
    admin_emails: tuple[str, ...] = ()
    editor_emails: tuple[str, ...] = ()

    @classmethod
    def from_env(cls) -> "Settings":
        load_env_file()
        settings = cls(
            environment=os.environ.get("ORL_WEB_ENV", "development").strip().lower(),
            database_url=os.environ.get("ORL_WEB_DATABASE_URL", "sqlite:///./orl-web.db"),
            jwt_secret=os.environ.get("ORL_WEB_JWT_SECRET", _DEV_SECRET),
            jwt_issuer=os.environ.get("ORL_WEB_JWT_ISSUER", "orl-auth"),
            jwt_audience=os.environ.get("ORL_WEB_JWT_AUDIENCE", "orl-web"),
            question_limit_per_hour=int(os.environ.get("ORL_WEB_QUESTION_LIMIT_PER_HOUR", "5")),
            report_limit_per_hour=int(os.environ.get("ORL_WEB_REPORT_LIMIT_PER_HOUR", "10")),
            magic_link_limit_per_hour=int(os.environ.get("ORL_WEB_MAGIC_LINK_LIMIT_PER_HOUR", "5")),
            access_request_limit_per_hour=int(os.environ.get(
                "ORL_WEB_ACCESS_REQUEST_LIMIT_PER_HOUR", "60")),
            delivery_batch_size=int(os.environ.get("ORL_WEB_DELIVERY_BATCH_SIZE", "50")),
            access_mode=os.environ.get("ORL_WEB_ACCESS_MODE", "invite").strip().lower(),
            domains=_labels("ORL_WEB_DOMAINS") or _DEFAULT_DOMAINS,
            base_url=os.environ.get("ORL_WEB_BASE_URL", "http://127.0.0.1:8080").rstrip("/"),
            session_cookie_name=os.environ.get("ORL_WEB_SESSION_COOKIE_NAME", "truthlm_session"),
            session_days=int(os.environ.get("ORL_WEB_SESSION_DAYS", "30")),
            magic_link_minutes=int(os.environ.get("ORL_WEB_MAGIC_LINK_MINUTES", "15")),
            email_delivery=os.environ.get("ORL_WEB_EMAIL_DELIVERY", "console").strip().lower(),
            smtp_host=os.environ.get("ORL_WEB_SMTP_HOST", ""),
            smtp_port=int(os.environ.get("ORL_WEB_SMTP_PORT", "587")),
            smtp_username=os.environ.get("ORL_WEB_SMTP_USERNAME", ""),
            smtp_password=os.environ.get("ORL_WEB_SMTP_PASSWORD", ""),
            smtp_from_email=os.environ.get("ORL_WEB_SMTP_FROM_EMAIL", ""),
            smtp_starttls=os.environ.get("ORL_WEB_SMTP_STARTTLS", "true").lower() in {"1", "true", "yes"},
            admin_emails=_emails("ORL_WEB_ADMIN_EMAILS"),
            editor_emails=_emails("ORL_WEB_EDITOR_EMAILS"),
        )
        settings.validate()
        return settings

    @property
    def domain_labels(self) -> dict[str, str]:
        return {domain_key(label): label for label in self.domains}

    def validate(self) -> None:
        if self.environment == "production":
            if self.jwt_secret == _DEV_SECRET or len(self.jwt_secret) < 32:
                raise ValueError("production ORL_WEB_JWT_SECRET must be at least 32 characters")
            if not self.database_url.startswith(("postgresql://", "postgresql+psycopg://")):
                raise ValueError("production ORL Web requires PostgreSQL")
            if not self.base_url.startswith("https://"):
                raise ValueError("production ORL_WEB_BASE_URL must use HTTPS")
            if self.email_delivery != "smtp" or not self.smtp_host or not self.smtp_from_email:
                raise ValueError("production email delivery requires SMTP host and from address")
        if self.email_delivery not in {"console", "smtp"}:
            raise ValueError("email delivery must be console or smtp")
        if self.access_mode not in ACCESS_MODES:
            raise ValueError("access mode must be invite or open")
        keys = [domain_key(label) for label in self.domains]
        if not keys or not all(keys) or len(set(keys)) != len(keys) or \
                UNASSIGNED_DOMAIN in keys or max(map(len, keys)) > 64:
            raise ValueError("domains must be distinct non-empty labels")
        if min(self.question_limit_per_hour, self.report_limit_per_hour,
               self.magic_link_limit_per_hour, self.access_request_limit_per_hour) < 1:
            raise ValueError("rate limits must be positive")
        if not 1 <= self.delivery_batch_size <= 1000:
            raise ValueError("delivery batch size must be between 1 and 1000")
        if self.session_days < 1 or self.magic_link_minutes < 1:
            raise ValueError("authentication lifetimes must be positive")


def _emails(name: str) -> tuple[str, ...]:
    return tuple(sorted({value.strip().lower() for value in os.environ.get(name, "").split(",")
                         if value.strip()}))


def _labels(name: str) -> tuple[str, ...]:
    labels = (" ".join(value.split()) for value in os.environ.get(name, "").split(","))
    return tuple(dict.fromkeys(label for label in labels if label))
