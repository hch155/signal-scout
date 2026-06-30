"""add facebook_user_id + session_token_version to user

facebook_user_id binds a Facebook OAuth identity to a user explicitly
(linked from /account after a password step-up) so Facebook login matches
by account id, never by an unverified email — closing the account-takeover
vector. session_token_version is bumped on password change/reset so every
session minted earlier is evicted (global sign-out on credential change).

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-30
"""
from alembic import op
import sqlalchemy as sa

revision = '0005'
down_revision = '0004'
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.add_column(sa.Column('facebook_user_id', sa.String(length=64), nullable=True))
        batch_op.add_column(sa.Column('session_token_version', sa.Integer(), nullable=False, server_default='0'))
        batch_op.create_index('ix_user_facebook_user_id', ['facebook_user_id'], unique=True)


def downgrade() -> None:
    with op.batch_alter_table('user', schema=None) as batch_op:
        batch_op.drop_index('ix_user_facebook_user_id')
        batch_op.drop_column('session_token_version')
        batch_op.drop_column('facebook_user_id')
