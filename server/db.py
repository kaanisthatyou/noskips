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


def normalize_database_url(url):
    """Make a connection string copied off a dashboard actually connectable.

    Two rewrites, both of them things you'd otherwise discover as a stack trace:

    * ``postgres://`` is the scheme Neon and Heroku still hand out and the one
      SQLAlchemy dropped.
    * ``postgresql://`` with no driver resolves to **psycopg2**, and what's
      installed here is psycopg **3** (``psycopg[binary]`` in the server's
      requirements). Pasting Neon's URL unchanged gets you
      ``ModuleNotFoundError: No module named 'psycopg2'`` from alembic and from
      the first request on Vercel. An explicitly chosen driver is left alone.
    """
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


DEFAULT_DATABASE_URL = "sqlite:///noskips-dev.db"


def database_url():
    """The connection string, with a blank one treated as no connection string.

    ``or`` rather than a ``get`` default on purpose. .env.example ships every
    key present and empty, and docs/SERVER.md says to copy it verbatim — which
    puts ``DATABASE_URL=""`` in the environment. A two-argument ``get`` only
    falls back when the key is *absent*, so following the documented setup
    handed SQLAlchemy an empty string and 500'd every request on a fresh
    checkout. Blank means unset here, everywhere it means anything.
    """
    return normalize_database_url(os.environ.get("DATABASE_URL") or DEFAULT_DATABASE_URL)


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
