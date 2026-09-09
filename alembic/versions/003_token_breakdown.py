"""Add token sub-category columns to usage_events

Revision ID: 003_token_breakdown
Revises: 002_stripe_events
Create Date: 2026-08-30 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '003_token_breakdown'
down_revision: Union[str, None] = '002_stripe_events'
branch_labels: Union[str, None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.add_column('usage_events', sa.Column('input_tokens', sa.Integer(), server_default='0', nullable=False))
    op.add_column('usage_events', sa.Column('cached_input_tokens', sa.Integer(), server_default='0', nullable=False))
    op.add_column('usage_events', sa.Column('output_tokens', sa.Integer(), server_default='0', nullable=False))
    op.add_column('usage_events', sa.Column('reasoning_tokens', sa.Integer(), server_default='0', nullable=False))


def downgrade() -> None:
    op.drop_column('usage_events', 'reasoning_tokens')
    op.drop_column('usage_events', 'output_tokens')
    op.drop_column('usage_events', 'cached_input_tokens')
    op.drop_column('usage_events', 'input_tokens')
