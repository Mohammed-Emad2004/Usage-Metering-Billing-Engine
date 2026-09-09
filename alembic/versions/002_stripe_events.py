"""Add stripe_events table for webhook deduplication

Revision ID: 002_stripe_events
Revises: 001_initial
Create Date: 2026-08-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '002_stripe_events'
down_revision: Union[str, None] = '001_initial'
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.create_table('stripe_events',
    sa.Column('id', sa.String(), nullable=False),
    sa.Column('stripe_event_id', sa.String(), nullable=False),
    sa.Column('event_type', sa.String(), nullable=False),
    sa.Column('payload', sa.Text(), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('CURRENT_TIMESTAMP'), nullable=False),
    sa.PrimaryKeyConstraint('id'),
    sa.UniqueConstraint('stripe_event_id', name='uq_stripe_event_id')
    )
    op.create_index(op.f('ix_stripe_events_id'), 'stripe_events', ['id'], unique=False)
    op.create_index(op.f('ix_stripe_events_stripe_event_id'), 'stripe_events', ['stripe_event_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_stripe_events_stripe_event_id'), table_name='stripe_events')
    op.drop_index(op.f('ix_stripe_events_id'), table_name='stripe_events')
    op.drop_table('stripe_events')
