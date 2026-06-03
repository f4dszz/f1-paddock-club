"""Alembic env — wired to backend/db.Base.metadata so autogenerate sees our models."""
from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

# Ensure `backend/` is importable as the top-level package root.
BACKEND_DIR = Path(__file__).resolve().parents[1]
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from db import Base, _database_url  # noqa: E402
import models  # noqa: F401,E402  (registers ORM classes onto Base.metadata)

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def _resolved_url() -> str:
    """Use db._database_url() which already resolves TEST_DATABASE_URL > DATABASE_URL > SQLite."""
    ini_url = config.get_main_option("sqlalchemy.url") or ""
    if ini_url and not ini_url.startswith("driver://"):
        return ini_url
    return _database_url()


def run_migrations_offline() -> None:
    context.configure(
        url=_resolved_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


# Arbitrary but stable 64-bit key for the Postgres advisory lock that
# serializes `alembic upgrade head`. Any value works as long as every
# replica uses the SAME one.
_MIGRATION_ADVISORY_LOCK_KEY = 727_2026


def run_migrations_online() -> None:
    # CONCURRENCY (BS-04): migrations run inline in the deploy start command
    # (railway.json), so two replicas booting at once could both call
    # `alembic upgrade head` and race on DDL. On Postgres we take a session-
    # level advisory lock first: the second replica blocks until the first
    # finishes, then sees head is current and applies nothing. On SQLite (and
    # any non-Postgres dialect) this is a safe no-op — local dev/tests run a
    # single process, so no lock is needed.
    #
    # NOTE: this guards against the concurrent-boot race only; it assumes the
    # service still runs effectively single-instance for migrations. A
    # dedicated release/pre-deploy migration phase remains the deeper fix.
    from sqlalchemy import text

    section = config.get_section(config.config_ini_section, {})
    section["sqlalchemy.url"] = _resolved_url()
    connectable = engine_from_config(section, prefix="sqlalchemy.", poolclass=pool.NullPool)
    with connectable.connect() as connection:
        is_postgres = connection.dialect.name == "postgresql"
        if is_postgres:
            connection.exec_driver_sql(
                f"SELECT pg_advisory_lock({_MIGRATION_ADVISORY_LOCK_KEY})"
            )
        try:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=connection.dialect.name == "sqlite",
            )
            with context.begin_transaction():
                context.run_migrations()
        finally:
            if is_postgres:
                # Release the advisory lock so the next replica can proceed.
                connection.exec_driver_sql(
                    f"SELECT pg_advisory_unlock({_MIGRATION_ADVISORY_LOCK_KEY})"
                )


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
