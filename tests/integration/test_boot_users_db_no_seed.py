"""Prod-safety for change 3: the users.db boot path (Alembic upgrade +
create_all, with NO seed-from-image) must never wipe an existing
populated mount."""
import sqlite3

from db_migrations import upgrade_users_db


def _row_count(db_path, table):
    conn = sqlite3.connect(db_path)
    try:
        return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        conn.close()


def test_boot_preserves_existing_user_rows(tmp_path):
    """Build a populated users.db, run the boot upgrade path against it, and
    assert the existing user row is still there afterwards (not wiped)."""
    db_path = str(tmp_path / "users.db")

    # First boot creates the schema from the migrations on a fresh file.
    upgrade_users_db(db_path)
    assert "user" in _table_names(db_path)

    # Populate it with a user (simulating live prod data).
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO user "
        "(email, password_hash, role, status, totp_enabled, "
        " failed_login_attempts, email_alerts_enabled) "
        "VALUES ('keep-me@example.com', 'x', 'user', 'active', 0, 0, 1)"
    )
    conn.commit()
    conn.close()
    assert _row_count(db_path, "user") == 1

    # Re-run the boot upgrade (idempotent no-op) — the seed block is gone,
    # so nothing should overwrite the file.
    upgrade_users_db(db_path)

    assert _row_count(db_path, "user") == 1
    survivor = sqlite3.connect(db_path).execute(
        "SELECT email FROM user"
    ).fetchone()[0]
    assert survivor == "keep-me@example.com"


def _table_names(db_path):
    conn = sqlite3.connect(db_path)
    try:
        return {r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )}
    finally:
        conn.close()


def test_fresh_mount_gets_schema_from_alembic(tmp_path):
    """On a brand-new mount (no baked DB copied in), Alembic builds the full
    schema including the stats_snapshot table from migration 0003."""
    db_path = str(tmp_path / "fresh-users.db")
    upgrade_users_db(db_path)
    tables = _table_names(db_path)
    assert "user" in tables
    assert "stats_snapshot" in tables
    assert "alembic_version" in tables
