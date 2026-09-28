"""Database engine and transaction dependencies."""
from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from .config import Settings


def make_engine(database_url: str):
    kwargs = {"pool_pre_ping": True}
    if database_url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
    return create_engine(database_url, **kwargs)


def make_session_factory(engine):
    return sessionmaker(bind=engine, class_=Session, expire_on_commit=False, autoflush=False)


def default_session_factory():
    settings = Settings.from_env()
    return make_session_factory(make_engine(settings.database_url))


def session_dependency(factory):
    def get_session() -> Iterator[Session]:
        with factory() as session:
            yield session
    return get_session
