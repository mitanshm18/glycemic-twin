"""Engine and session factory. One engine per process; one session per request."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


def make_engine(url: str) -> Engine:
    # hide_parameters: database errors never carry bound values (tokens' hashes, identifiers) into
    # exception messages, and so never into logs
    return create_engine(url, pool_pre_ping=True, future=True, hide_parameters=True)


def make_sessionmaker(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, autoflush=False)


@contextmanager
def session_scope(factory: sessionmaker[Session]) -> Iterator[Session]:
    """Commit on success, roll back on any exception."""
    session = factory()
    try:
        yield session
        session.commit()
    except BaseException:
        session.rollback()
        raise
    finally:
        session.close()
