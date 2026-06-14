"""add stats_snapshot table to users.db

Replaces the boot-merged stats_history.jsonl file. Monthly /stats
aggregate snapshots now live in users.db so MoM deltas + the trend
chart survive on the same persistent mount as the rest of the user
data, with no bespoke JSONL dedup on boot.

snapshot_key is the UKE data date (YYYY-MM-DD) — it sorts
chronologically as a string and is UNIQUE so re-recording the same
refresh is a no-op.
"""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'stats_snapshot',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('snapshot_key', sa.Text(), nullable=False),
        sa.Column('recorded_at', sa.Text(), nullable=True),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('snapshot_key'),
    )


def downgrade() -> None:
    op.drop_table('stats_snapshot')
