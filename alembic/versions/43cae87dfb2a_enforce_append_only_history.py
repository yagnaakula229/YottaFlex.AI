"""enforce append-only history

Revision ID: 43cae87dfb2a
Revises: ca1b7e84c2f9
Create Date: 2026-10-26 20:34:42.252652
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '43cae87dfb2a'
down_revision: Union[str, None] = 'ca1b7e84c2f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

OPERATIONAL_TABLES = (
    'consent_event',
    'cart_event',
    'message_event',
    'audit_event',
    'attribution_decision',
    'attribution_candidate',
)


def upgrade() -> None:
    op.execute("""
        CREATE FUNCTION public.prevent_row_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION '% rows are append-only', TG_TABLE_NAME
                USING ERRCODE = '23514';
        END;
        $$
    """)
    for table_name in OPERATIONAL_TABLES:
        op.execute(
            f'CREATE TRIGGER trg_{table_name}_append_only '
            f'BEFORE UPDATE OR DELETE ON public."{table_name}" '
            'FOR EACH ROW EXECUTE FUNCTION public.prevent_row_mutation()'
        )
    op.execute(
        'CREATE TRIGGER trg_ground_truth_label_append_only '
        'BEFORE UPDATE OR DELETE ON evaluation."ground_truth_label" '
        'FOR EACH ROW EXECUTE FUNCTION public.prevent_row_mutation()'
    )


def downgrade() -> None:
    for table_name in OPERATIONAL_TABLES:
        op.execute(f'DROP TRIGGER trg_{table_name}_append_only ON public."{table_name}"')
    op.execute('DROP TRIGGER trg_ground_truth_label_append_only ON evaluation."ground_truth_label"')
    op.execute('DROP FUNCTION public.prevent_row_mutation()')