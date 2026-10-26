"""link consent projections to history

Revision ID: d47068fc7722
Revises: 60df5e8d2123
Create Date: 2026-10-26 22:07:33.907105
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'd47068fc7722'
down_revision: Union[str, None] = '60df5e8d2123'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('consent', sa.Column('last_event_id', sa.String(length=64), nullable=True))
    op.execute("""
        UPDATE consent AS projection
        SET last_event_id = (
            SELECT event.business_id
            FROM consent_event AS event
            WHERE event.customer_id = projection.customer_id
              AND event.channel = projection.channel
            ORDER BY event.occurred_at DESC, event.business_id DESC
            LIMIT 1
        )
        WHERE EXISTS (
            SELECT 1
            FROM consent_event AS event
            WHERE event.customer_id = projection.customer_id
              AND event.channel = projection.channel
        )
    """)
    op.create_foreign_key('fk_consent_last_event', 'consent', 'consent_event', ['last_event_id'], ['business_id'])


def downgrade() -> None:
    op.drop_constraint('fk_consent_last_event', 'consent', type_='foreignkey')
    op.drop_column('consent', 'last_event_id')