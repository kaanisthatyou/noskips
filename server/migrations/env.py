"""Alembic environment.

Reads DATABASE_URL from the environment so the same migrations run against a
local SQLite file and against Neon in production with no config edits. Neon's
pooled connection string is what production should use — see server/db.py.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from server.db import database_url as database_url_from_env
from server.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# one definition of what a pasted Neon URL turns into, shared with the app —
# a migration that connects differently from the server is its own bug
database_url = database_url_from_env()
config.set_main_option("sqlalchemy.url", database_url)

target_metadata = Base.metadata


def run_migrations_offline():
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online():
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # batch mode keeps SQLite able to run ALTERs, so a dev can rehearse
            # a migration locally before it touches Postgres
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
