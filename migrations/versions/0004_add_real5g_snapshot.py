"""add real_five_g_snapshot table to users.db

Monthly 3.5 GHz (n78 / C-band) rollout snapshots live in users.db so the
/rollout MoM deltas + trend chart survive on the same persistent mount as
the rest of the user data. Mirrors 0003_add_stats_snapshot.

snapshot_key is the UKE data date (YYYY-MM-DD) — it sorts chronologically
as a string and is UNIQUE so re-recording the same refresh is a no-op.
"""
from alembic import op
import sqlalchemy as sa

revision = '0004'
down_revision = '0003'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'real_five_g_snapshot',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('snapshot_key', sa.Text(), nullable=False),
        sa.Column('recorded_at', sa.Text(), nullable=True),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('snapshot_key'),
    )


def downgrade() -> None:
    op.drop_table('real_five_g_snapshot')
