"""Alembic boot runner for users.db (replaces the ensure_*_columns era).

Self-healing, idempotent, runs on every boot before db.create_all():

- Fresh file (no tables): `upgrade head` builds the full schema from
  migrations; the subsequent create_all() is a no-op.
- Pre-Alembic prod DB (tables exist, no alembic_version): stamped with
  the baseline revision first, then upgraded — existing data untouched.
- Already-migrated DB: upgrade is a no-op.

stations.db is deliberately out of scope — it is rebuilt from UKE data
monthly, never migrated.
"""
import logging
import os

logger = logging.getLogger(__name__)

BASELINE_REVISION = "0001"


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def upgrade_users_db(users_db_path: str) -> None:
    from alembic import command
    from alembic.config import Config
    from alembic.util.exc import CommandError
    from sqlalchemy import create_engine, inspect

    root = _repo_root()
    cfg = Config(os.path.join(root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(root, "migrations"))
    cfg.set_main_option("sqlalchemy.url", f"sqlite:///{users_db_path}")

    engine = create_engine(f"sqlite:///{users_db_path}")
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    if "alembic_version" not in tables and "user" in tables:
        logger.info("users.db pre-dates Alembic — stamping baseline %s",
                    BASELINE_REVISION)
        command.stamp(cfg, BASELINE_REVISION)

    try:
        command.upgrade(cfg, "head")
    except CommandError as exc:
        # users.db is ahead of this build (e.g. a rollback to an older image
        # after a forward, additive migration). Additive migrations are
        # forward-compatible, so continue on the existing schema instead of
        # crash-looping the way the 6260a5e rollback did on revision 0004.
        if "Can't locate revision" not in str(exc):
            raise
        logger.warning(
            "users.db revision is ahead of this build's migrations — "
            "continuing on the existing schema (%s)", exc)
