"""listening time, coverage, and the name a provider knows you by

Revision ID: a1b2c3d4e5f6
Revises: 51d87fdefb28
Create Date: 2026-08-18

Three additive columns, all with defaults, so an old widget that knows nothing
about any of them keeps syncing unchanged.

``server_default`` matters on the two rating columns: there are already rows,
and they are NOT NULL. Without it the ALTER fails on Postgres the moment the
table isn't empty — which, in production, it isn't.
"""

from alembic import op
import sqlalchemy as sa


revision = 'a1b2c3d4e5f6'
down_revision = '51d87fdefb28'
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('identities', schema=None) as batch_op:
        batch_op.add_column(sa.Column('username_at_provider', sa.String(length=64), nullable=True))

    with op.batch_alter_table('ratings', schema=None) as batch_op:
        batch_op.add_column(
            sa.Column('listened_ms', sa.Integer(), nullable=False, server_default='0')
        )
        batch_op.add_column(
            sa.Column('coverage', sa.Numeric(precision=4, scale=3), nullable=False,
                      server_default='0')
        )

    # The leaderboards read these two together, per user. Everything already
    # rated is history, so this index is what keeps the boards one scan of a
    # covering index rather than a walk of every rating ever stamped.
    op.create_index('ix_ratings_listening', 'ratings', ['user_id', 'coverage'], unique=False)


def downgrade():
    op.drop_index('ix_ratings_listening', table_name='ratings')
    with op.batch_alter_table('ratings', schema=None) as batch_op:
        batch_op.drop_column('coverage')
        batch_op.drop_column('listened_ms')
    with op.batch_alter_table('identities', schema=None) as batch_op:
        batch_op.drop_column('username_at_provider')
