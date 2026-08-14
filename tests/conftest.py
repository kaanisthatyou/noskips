import os

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker


@pytest.fixture(scope="session", autouse=True)
def never_touch_the_real_library(tmp_path_factory):
    """Point the widget's data directory at a throwaway folder, for every test.

    Belt and braces on top of each fixture's own isolation. Importing app.py
    creates and writes to whatever DATA_DIR resolves to, and the default is the
    library sitting next to the source — so a test that merely imports the
    module can quietly add rows to somebody's real shelf. That happened once;
    this makes it impossible to happen twice.
    """
    root = tmp_path_factory.mktemp("widget-data")
    os.environ.setdefault("NOSKIPS_DATA_DIR", str(root / "data"))
    os.environ.setdefault("NOSKIPS_COVERS_DIR", str(root / "covers"))
    yield

from server import db as database
from server.emailer import ConsoleSender
from server.models import Base, User


@pytest.fixture
def session():
    """A throwaway SQLite database per test.

    The models deliberately stick to portable types so the suite runs with no
    Postgres, no Docker and no network — which keeps CI free and the feedback
    loop under a second.
    """
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    with Session(engine) as s:
        yield s


@pytest.fixture
def users(session):
    """Three people, ready to disagree about music."""
    return _make_users(session)


def _make_users(session):
    made = []
    for handle in ("kaan", "mert", "asli"):
        u = User(handle=handle, handle_ci=handle, display_name=handle)
        session.add(u)
        made.append(u)
    session.flush()
    return made


# ------------------------------------------------------------ the whole app ----


@pytest.fixture
def app(tmp_path, monkeypatch):
    """The real Flask app, on a real (temporary) database.

    A file rather than :memory: because every request opens its own session,
    and an in-memory SQLite database is private to a single connection.
    """
    url = f"sqlite:///{tmp_path / 'test.db'}"
    monkeypatch.setenv("DATABASE_URL", url)

    engine = create_engine(url)
    Base.metadata.create_all(engine)

    # rebuild the module-level engine against this test's database
    database._engine = engine
    database._Session = sessionmaker(bind=engine, class_=Session, expire_on_commit=False)

    from server.factory import create_app

    mailbox = ConsoleSender()
    application = create_app({"SECRET_KEY": "test", "EMAILER": mailbox, "TESTING": True})
    application.mailbox = mailbox
    yield application

    database._engine = None
    database._Session = None


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def db(app):
    """A session onto the same database the app is using, for arranging state
    and for asserting what actually landed."""
    with Session(database._engine) as s:
        yield s
