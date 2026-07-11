"""Database engine and session management.

SQLite via SQLAlchemy 2.0 + SQLModel. The DB file lives under backend/data/
(gitignored). Schema is created on first run via init_db().
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import event
from sqlalchemy.orm import sessionmaker
from sqlmodel import Session, SQLModel, create_engine

from paios.config import DATA_DIR, get_settings


def _ensure_data_dir() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)


# --- Sync engine (used for tooling, migrations, tests) ----------------------

_sync_engine = None
_sync_engine_lock = threading.RLock()
_sync_session_factory: sessionmaker[Session] | None = None


def get_sync_engine():
    global _sync_engine
    if _sync_engine is None:
        with _sync_engine_lock:
            if _sync_engine is None:
                _ensure_data_dir()
                url = get_settings().database_url
                sync_url = url.replace("sqlite:///", "sqlite:///").replace("sqlite+aiosqlite://", "sqlite://")
                _sync_engine = create_engine(
                    sync_url, echo=False,
                    connect_args={"check_same_thread": False, "timeout": 5},
                    pool_pre_ping=True,
                )

                @event.listens_for(_sync_engine, "connect")
                def _set_sqlite_pragma(dbapi_connection, connection_record):
                    cursor = dbapi_connection.cursor()
                    cursor.execute("PRAGMA journal_mode=WAL;")
                    cursor.execute("PRAGMA busy_timeout=5000;")
                    cursor.close()
    return _sync_engine


def reset_sync_engine() -> None:
    """Drop the cached engine. Use in tests to force a fresh engine."""
    global _sync_engine, _sync_session_factory
    with _sync_engine_lock:
        if _sync_engine is not None:
            _sync_engine.dispose()
        _sync_engine = None
        _sync_session_factory = None


def get_sync_session_factory() -> sessionmaker[Session]:
    global _sync_session_factory
    if _sync_session_factory is None:
        with _sync_engine_lock:
            if _sync_session_factory is None:
                _sync_session_factory = sessionmaker(bind=get_sync_engine(), class_=Session, expire_on_commit=False)
    return _sync_session_factory


@contextmanager
def sync_session_scope() -> Iterator[Session]:
    """Context manager that yields a Session and commits/rolls back on exit."""
    factory = get_sync_session_factory()
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# --- Init --------------------------------------------------------------------

def init_db() -> None:
    """Create all tables. Safe to call on every startup."""
    # Import models so SQLModel knows about them before create_all.
    from paios.db import models  # noqa: F401

    _ensure_data_dir()
    SQLModel.metadata.create_all(get_sync_engine())
