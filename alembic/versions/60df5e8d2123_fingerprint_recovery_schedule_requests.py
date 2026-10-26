"""fingerprint recovery schedule requests

Revision ID: 60df5e8d2123
Revises: e895a794f154
Create Date: 2026-10-26 21:54:39.119547
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '60df5e8d2123'
down_revision: Union[str, None] = 'e895a794f154'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('send_schedule', sa.Column('request_fingerprint', sa.String(length=64), nullable=True))
    op.execute("""
        UPDATE send_schedule
        SET request_fingerprint = md5(idempotency_key) || md5(idempotency_key)
    """)
    op.alter_column('send_schedule', 'request_fingerprint', nullable=False)


def downgrade() -> None:
    op.drop_column('send_schedule', 'request_fingerprint')