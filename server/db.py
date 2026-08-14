"""Engine and session handling, shaped for serverless.

On Vercel every request may land in a fresh, short-lived Python process, so the
usual long-lived connection pool is worse than useless — it holds Postgres
connections that the next invocation can't reach. Instead: ``NullPool`` here and
Neon's *pooled* connection string (the one with ``-pooler`` in the host), which
puts PgBouncer in front and does the real pooling outside our process.
"""

import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import NullPool

_engine = None
_Session = None


def database_url():
    url = os.environ.get("DATABASE_URL", "sqlite:///noskips-dev.db")
    # Neon and Heroku-style URLs still use the scheme SQLAlchemy dropped
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def engine():
    global _engine, _Session
    if _engine is None:
        url = database_url()
        kwargs = {"pool_pre_ping": True, "future": True}
        if url.startswith("postgresql"):
            kwargs["poolclass"] = NullPool
        _engine = create_engine(url, **kwargs)
        _Session = sessionmaker(bind=_engine, class_=Session, expire_on_commit=False)
    return _engine


@contextmanager
def session_scope():
    """A transaction that commits on success and rolls back on anything else."""
    engine()
    s = _Session()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
