from __future__ import annotations

import logging
from collections.abc import Generator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from duplex_bot.config import AppConfig
from duplex_bot.db.models import Base

logger = logging.getLogger(__name__)

# Postgres deployments keep tenant tables in a dedicated schema for tidiness.
# SQLite has no schema concept, so this is ignored there.
SCHEMA = "duplex"


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    config = AppConfig()
    is_sqlite = config.is_sqlite

    connect_args = {"check_same_thread": False} if is_sqlite else {}
    engine = create_engine(
        config.database_url,
        pool_pre_ping=not is_sqlite,
        connect_args=connect_args,
        future=True,
    )

    if is_sqlite:
        # WAL + a busy timeout keep concurrent voice sessions from tripping over
        # the single-writer file lock under load.
        @event.listens_for(engine, "connect")
        def _set_sqlite_pragmas(dbapi_connection, _record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA busy_timeout=5000")
            cursor.close()
        return engine

    # Postgres: pin ALL of our (schema-less) tables into the dedicated `duplex`
    # schema via a translate map. This is what keeps the product safe on shared
    # managed databases (e.g. a Citus/Cosmos `citus` DB that already has its own
    # `public.users`): our DDL and queries always target `duplex.*`, never
    # colliding with whatever lives in `public`.
    return engine.execution_options(schema_translate_map={None: SCHEMA})


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return sessionmaker(
        bind=get_engine(), autoflush=False, autocommit=False, expire_on_commit=False
    )


def init_db() -> None:
    """Create all tables on first boot. Idempotent and dialect-aware.

    This makes the product zero-config: on SQLite the database file and all
    tables are created automatically; on Postgres the ``duplex`` schema is
    created if missing and then all tables are materialised. No manual
    migration step is required to get a working single container.
    """
    config = AppConfig()
    engine = get_engine()

    if not config.is_sqlite:
        with engine.begin() as conn:
            conn.execute(text(f"CREATE SCHEMA IF NOT EXISTS {SCHEMA}"))

    Base.metadata.create_all(bind=engine)
    logger.info(
        "Database ready (%s)",
        "sqlite" if config.is_sqlite else "postgresql",
    )


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Transactional session context manager: commit on success, rollback on error."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency that yields a request-scoped session."""
    session = get_session_factory()()
    try:
        yield session
    finally:
        session.close()
