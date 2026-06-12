import os
import sys

from alembic import context
from sqlalchemy import create_engine

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "src"))

import models  # noqa: F401,E402  (registers tables on db.metadatas)
from database import db  # noqa: E402

config = context.config

# Same resolution as src/app.py: USERS_DB_PATH env, else src/instance/users.db.
target_metadata = db.metadatas["users"]


def _users_db_url() -> str:
    url = config.get_main_option("sqlalchemy.url")
    if url:
        return url
    path = os.getenv("USERS_DB_PATH") or os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "src", "instance", "users.db",
    )
    return f"sqlite:///{path}"


def run_migrations_offline() -> None:
    context.configure(
        url=_users_db_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is not None:
        context.configure(
            connection=connectable,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
        return
    engine = create_engine(_users_db_url())
    with engine.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
