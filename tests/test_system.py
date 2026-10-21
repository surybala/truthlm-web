from __future__ import annotations

import os
import re
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from orl_web.config import Settings
from orl_web.models import AuditEvent, MetricsSnapshot, User


ROOT = Path(__file__).resolve().parents[1]
REQ = re.compile(r"^\s*-\s+\*\*([A-Z0-9]+-[A-Z0-9]+-\d{3})\*\*", re.M)
MARK = re.compile(r"mark\.spec\(([^)]*)\)")
ID = re.compile(r"[\"']([A-Z0-9]+-[A-Z0-9]+-\d{3})[\"']")


@pytest.mark.spec("WEB-ARCH-001")
def test_project_does_not_import_core_modules():
    source = "\n".join(path.read_text() for path in (ROOT / "orl_web").rglob("*.py"))
    assert not re.search(r"(?:from|import)\s+orl(?:\.|\s|$)", source)
    assert "catalog.db" not in source and "QDRANT" not in source


@pytest.mark.spec("WEB-OPS-001")
def test_initial_migration_upgrades_and_downgrades(tmp_path):
    db = tmp_path / "migration.db"
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{db}")
    command.upgrade(cfg, "20260928_0008")
    engine = __import__("sqlalchemy").create_engine(f"sqlite:///{db}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT INTO users (id, external_subject, email, role, voting_eligible, created_at) "
            "VALUES ('u-paid', 'email:paid@example.org', 'paid@example.org', 'paid', 1, "
            "'2026-09-28 00:00:00')")
    command.upgrade(cfg, "head")
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT role FROM users WHERE id = 'u-paid'").scalar() == "user"
    tables = set(inspect(engine).get_table_names())
    assert {"users", "question_submissions", "question_clusters", "cluster_memberships",
            "readiness_assessments", "metrics_snapshots", "publication_bundles",
            "articles", "article_revisions", "audit_events", "magic_link_tokens",
            "browser_sessions", "question_reports", "research_subscriptions",
            "feed_access_tokens", "access_requests", "email_deliveries"} <= tables
    assert not {"votes", "weekly_cycles", "cycle_selections"} & tables
    inspector = inspect(engine)
    users = {column["name"] for column in inspector.get_columns("users")}
    assert "email_opt_out_at" in users and "voting_eligible" not in users
    submissions = {column["name"] for column in inspector.get_columns("question_submissions")}
    assert not {"answer", "answered_at"} & submissions
    assert "domain" in {column["name"] for column in inspector.get_columns("question_clusters")}
    unique = {tuple(item["column_names"]) for item in inspector.get_unique_constraints("email_deliveries")}
    assert ("user_id", "article_id") in unique
    command.downgrade(cfg, "20260928_0008")
    restored = set(inspect(engine).get_table_names())
    assert {"votes", "weekly_cycles", "cycle_selections"} <= restored and "email_deliveries" not in restored
    with engine.connect() as connection:
        ddl = connection.exec_driver_sql(
            "SELECT sql FROM sqlite_master WHERE name = 'uq_one_open_cycle'").scalar()
    assert "WHERE state = 'open'" in ddl
    command.downgrade(cfg, "base")
    assert set(inspect(engine).get_table_names()) <= {"alembic_version"}
    engine.dispose()


@pytest.mark.spec("WEB-OPS-001")
def test_migrations_accept_percent_encoded_database_url(tmp_path, monkeypatch):
    # Hosted Postgres passwords are percent-encoded in the URL (@ -> %40); alembic's ConfigParser
    # treats a bare "%" as interpolation, so env.py must pass the URL through unchanged.
    (tmp_path / "a@b").mkdir()
    monkeypatch.setenv("ORL_WEB_DATABASE_URL", f"sqlite:///{tmp_path}/a%40b/encoded.db")
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    command.upgrade(cfg, "head")
    engine = __import__("sqlalchemy").create_engine(f"sqlite:///{tmp_path}/a@b/encoded.db")
    assert {"users", "articles", "email_deliveries"} <= set(inspect(engine).get_table_names())
    engine.dispose()


@pytest.mark.spec("WEB-OPS-001")
def test_immutable_models_reject_application_updates(session_factory):
    with session_factory() as session:
        user = User(external_subject="actor", role="admin")
        session.add(user)
        session.flush()
        event = AuditEvent(actor_id=user.id, action="test", target_type="test", target_id="1")
        metric = MetricsSnapshot(snapshot_id="snapshot", generated_at=__import__("datetime").datetime.now(
            __import__("datetime").UTC), content_sha256="a" * 64, payload={})
        session.add_all([event, metric])
        session.commit()
        event.action = "changed"
        with pytest.raises(ValueError, match="immutable"):
            session.commit()


@pytest.mark.spec("WEB-OPS-002")
def test_project_env_file_is_loaded_without_overriding_the_environment(tmp_path, monkeypatch):
    from orl_web import config

    env_file = tmp_path / ".env"
    env_file.write_text("ORL_WEB_ADMIN_EMAILS=Owner@Example.org\nORL_WEB_ACCESS_MODE=open\n")
    monkeypatch.setattr(config, "PROJECT_ENV_FILE", env_file)
    monkeypatch.setenv("ORL_WEB_ADMIN_EMAILS", "placeholder")
    monkeypatch.delenv("ORL_WEB_ADMIN_EMAILS")  # restored to absent after the test
    monkeypatch.setenv("ORL_WEB_ACCESS_MODE", "invite")
    Settings.from_env()
    assert "ORL_WEB_ADMIN_EMAILS" not in os.environ  # the suite runs with ORL_WEB_DOTENV=0
    monkeypatch.setenv("ORL_WEB_DOTENV", "1")
    settings = Settings.from_env()
    assert settings.admin_emails == ("owner@example.org",)
    assert settings.access_mode == "invite"
    assert config.PROJECT_ENV_FILE.name == ".env"
    monkeypatch.undo()
    assert Path(config.PROJECT_ENV_FILE) == ROOT / ".env"
    assert "load_env_file()" in (ROOT / "migrations" / "env.py").read_text()


@pytest.mark.spec("WEB-OPS-002")
def test_suite_does_not_inherit_web_configuration():
    assert os.environ["ORL_WEB_DOTENV"] == "0"
    assert not [name for name in os.environ if name.startswith("ORL_WEB_") and name != "ORL_WEB_DOTENV"]


@pytest.mark.spec("WEB-OPS-003")
def test_static_assets_carry_explicit_cache_headers(client):
    year, short = "public, max-age=31536000, immutable", "public, max-age=300"
    assert client.get("/static/site.css?v=20261020").headers["cache-control"] == year
    assert client.get("/static/site.css?v=").headers["cache-control"] == short
    plain = client.get("/static/auth.js")
    assert plain.status_code == 200 and plain.headers["cache-control"] == short
    revalidated = client.get("/static/auth.js", headers={"If-None-Match": plain.headers["etag"]})
    assert revalidated.status_code == 304 and revalidated.headers["cache-control"] == short
    missing = client.get("/static/missing.js?v=1")
    assert missing.status_code == 404 and "immutable" not in missing.headers.get("cache-control", "")


@pytest.mark.spec("WEB-OPS-003")
def test_referenced_raster_images_exist_and_stay_small():
    static = ROOT / "orl_web" / "static"
    sources = [*(ROOT / "orl_web" / "templates").glob("*.html"), static / "site.css"]
    image = r"images/[\w./-]+\.(?:png|jpe?g|webp|gif|avif)"
    refs = {ref for source in sources for ref in re.findall(
        rf"/static/({image})|path=['\"]({image})['\"]", source.read_text()) for ref in ref if ref}
    assert refs, "found no raster image references; the pattern no longer matches the templates"
    for ref in sorted(refs):
        assert (static / ref).is_file(), f"{ref} is referenced but missing"
        assert (static / ref).stat().st_size <= 400_000, f"{ref} is {(static / ref).stat().st_size} bytes"


def test_spec_traceability():
    ids = REQ.findall((ROOT / "specs" / "SPEC-WEB.md").read_text())
    cited = set()
    for path in (ROOT / "tests").glob("test_*.py"):
        for marker in MARK.finditer(path.read_text()):
            cited.update(ID.findall(marker.group(1)))
    assert len(ids) == len(set(ids)) and set(ids) == cited


def test_production_configuration_rejects_unsafe_defaults():
    with pytest.raises(ValueError, match="JWT"):
        Settings(environment="production", database_url="postgresql+psycopg://db", jwt_secret="short").validate()
    with pytest.raises(ValueError, match="PostgreSQL"):
        Settings(environment="production", database_url="sqlite:///x",
                 jwt_secret="x" * 40).validate()
    with pytest.raises(ValueError, match="rate limits"):
        Settings(question_limit_per_hour=0).validate()
    with pytest.raises(ValueError, match="rate limits"):
        Settings(access_request_limit_per_hour=0).validate()
    for size in (0, 1001):
        with pytest.raises(ValueError, match="delivery batch"):
            Settings(delivery_batch_size=size).validate()
    with pytest.raises(ValueError, match="access mode"):
        Settings(access_mode="public").validate()
    for domains in ((), ("Economics", "economics"), ("!!!",), ("Unassigned",), ("x" * 65,)):
        with pytest.raises(ValueError, match="domains"):
            Settings(domains=domains).validate()


@pytest.mark.spec("WEB-Q-006", "WEB-ACCESS-001", "WEB-MAIL-003")
def test_access_mode_and_domains_are_read_from_the_environment(monkeypatch):
    monkeypatch.setenv("ORL_WEB_DELIVERY_BATCH_SIZE", "25")
    assert Settings.from_env().delivery_batch_size == 25
    monkeypatch.setenv("ORL_WEB_ACCESS_MODE", " Open ")
    monkeypatch.setenv("ORL_WEB_DOMAINS", "Physics, Materials  Science,,Physics")
    monkeypatch.setenv("ORL_WEB_ACCESS_REQUEST_LIMIT_PER_HOUR", "7")
    settings = Settings.from_env()
    assert settings.access_mode == "open" and settings.access_request_limit_per_hour == 7
    assert settings.domain_labels == {"physics": "Physics", "materials-science": "Materials Science"}
    monkeypatch.delenv("ORL_WEB_DOMAINS")
    assert list(Settings.from_env().domain_labels) == [
        "biology", "chemistry", "economics", "finance", "mathematics", "physics", "statistics"]
