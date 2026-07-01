"""de-identify submit_location_event: drop user_id, add logged_in, null out-of-PL coords

Privacy fix. The raw user_id FK stored on every logged-in map click made the
event directly-identified location history (joinable to user.email), which
contradicts the "pseudonymised" disclosure and the GDPR Art. 4(5) definition.
Replace it with a `logged_in` boolean (no account linkage at all). Also relax
lat/lng nullability and null the coordinates for out-of-Poland clicks — the
out-of-PL metric only needs the boolean, not a worldwide ~1km coordinate
(data minimisation, Art. 5(1)(c)).

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-01
"""
from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. add logged_in, carrying over the existing logged-in/anon split.
    with op.batch_alter_table('submit_location_event', schema=None) as batch_op:
        batch_op.add_column(sa.Column('logged_in', sa.Boolean(),
                                      nullable=False, server_default='0'))
    op.execute("UPDATE submit_location_event SET logged_in = 1 WHERE user_id IS NOT NULL")
    # 2. drop the reversible account link (and its index, so the batch
    #    rebuild doesn't try to recreate it) + relax coord nullability.
    with op.batch_alter_table('submit_location_event', schema=None) as batch_op:
        batch_op.drop_index('ix_submit_location_event_user_id')
        batch_op.drop_column('user_id')
        batch_op.alter_column('lat_bucket', existing_type=sa.Float(), nullable=True)
        batch_op.alter_column('lng_bucket', existing_type=sa.Float(), nullable=True)
    # 3. minimise: out-of-PL clicks keep only the boolean, not the coordinates
    #    (runs after the columns are nullable).
    op.execute("UPDATE submit_location_event SET lat_bucket = NULL, lng_bucket = NULL WHERE in_pl = 0")


def downgrade() -> None:
    # Lossy: user_id values and out-of-PL coordinates cannot be recovered.
    op.execute("UPDATE submit_location_event SET lat_bucket = 0.0 WHERE lat_bucket IS NULL")
    op.execute("UPDATE submit_location_event SET lng_bucket = 0.0 WHERE lng_bucket IS NULL")
    with op.batch_alter_table('submit_location_event', schema=None) as batch_op:
        batch_op.alter_column('lng_bucket', existing_type=sa.Float(), nullable=False)
        batch_op.alter_column('lat_bucket', existing_type=sa.Float(), nullable=False)
        batch_op.add_column(sa.Column('user_id', sa.Integer(), nullable=True))
        batch_op.create_index('ix_submit_location_event_user_id', ['user_id'], unique=False)
        batch_op.drop_column('logged_in')
