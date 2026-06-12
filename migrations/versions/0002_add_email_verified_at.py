"""add email_verified_at to user

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-11

Legacy accounts are backfilled with their registration_date: they
registered before verification existed, and retroactively flipping
them to unverified would cut off coverage alerts they already rely on.
NULL therefore means "signed up after this migration and never clicked
the link".
"""
from alembic import op
import sqlalchemy as sa

revision = '0002'
down_revision = '0001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('email_verified_at', sa.DateTime(), nullable=True))
    op.execute(
        "UPDATE user SET email_verified_at = registration_date "
        "WHERE email_verified_at IS NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_column('email_verified_at')
