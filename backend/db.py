"""SQLAlchemy engine + session management.

Reads DATABASE_URL from env (Railway auto-injects). Tests use
TEST_DATABASE_URL (SQLite in-memory or file) so they remain isolated.
Local dev with neither var set falls back to a SQLite file in
backend/_dev.sqlite3 (gitignored).
"""
from __future__ import annotations

import os
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


def _database_url() -> str:
    url = (
        os.environ.get("TEST_DATABASE_URL")
        or os.environ.get("DATABASE_URL")
        or "sqlite:///./_dev.sqlite3"
    )
    # Railway/Heroku inject bare `postgres://` / `postgresql://` URLs, which
    # SQLAlchemy maps to the psycopg2 dialect. We only ship psycopg3
    # (`psycopg[binary]`), so force the installed driver to avoid a
    # ModuleNotFoundError: psycopg2 at engine-build time (build + boot).
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def _make_engine():
    url = _database_url()
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, pool_pre_ping=True, future=True, connect_args=connect_args)


_engine = _make_engine()
SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_engine():
    return _engine


def rebind_for_tests(url: str) -> None:
    """Rebuild the global engine to point at a new URL. Test-only."""
    global _engine, SessionLocal
    os.environ["TEST_DATABASE_URL"] = url
    _engine = _make_engine()
    SessionLocal = sessionmaker(bind=_engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
