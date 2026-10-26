"""add recovery decision history

Revision ID: e895a794f154
Revises: ac27d186f70b
Create Date: 2026-10-26 21:50:53.940901
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'e895a794f154'
down_revision: Union[str, None] = 'ac27d186f70b'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table('recovery_decision',
    sa.Column('business_id', sa.String(length=64), nullable=False),
    sa.Column('decision_type', sa.String(length=20), nullable=False),
    sa.Column('cart_id', sa.String(length=64), nullable=False),
    sa.Column('customer_id', sa.String(length=64), nullable=False),
    sa.Column('channel', sa.String(length=32), nullable=False),
    sa.Column('campaign_id', sa.String(length=64), nullable=True),
    sa.Column('template_id', sa.String(length=64), nullable=True),
    sa.Column('outcome', sa.String(length=16), nullable=False),
    sa.Column('reason_code', sa.String(length=64), nullable=True),
    sa.Column('evaluated_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('policy_version', sa.String(length=64), nullable=False),
    sa.Column('configuration_hash', sa.String(length=64), nullable=False),
    sa.Column('evidence', postgresql.JSONB(astext_type=sa.Text()), nullable=False),
    sa.CheckConstraint("decision_type IN ('abandonment', 'eligibility')", name=op.f('ck_recovery_decision_decision_type_valid')),
    sa.CheckConstraint("outcome IN ('eligible', 'suppressed')", name=op.f('ck_recovery_decision_outcome_valid')),
    sa.CheckConstraint('length(channel) > 0', name=op.f('ck_recovery_decision_channel_not_empty')),
    sa.CheckConstraint('length(configuration_hash) = 64', name=op.f('ck_recovery_decision_configuration_hash_length')),
    sa.CheckConstraint('length(policy_version) > 0', name=op.f('ck_recovery_decision_policy_version_not_empty')),
    sa.ForeignKeyConstraint(['campaign_id'], ['campaign.business_id'], name='fk_recovery_decision_campaign'),
    sa.ForeignKeyConstraint(['cart_id'], ['cart.business_id'], name='fk_recovery_decision_cart'),
    sa.ForeignKeyConstraint(['customer_id'], ['customer.business_id'], name='fk_recovery_decision_customer'),
    sa.ForeignKeyConstraint(['template_id'], ['message_template.business_id'], name='fk_recovery_decision_template'),
    sa.PrimaryKeyConstraint('business_id', name=op.f('pk_recovery_decision'))
    )
    op.create_index('ix_recovery_decision_cart_evaluated', 'recovery_decision', ['cart_id', 'evaluated_at'], unique=False)
    op.create_index('ix_recovery_decision_customer_channel_evaluated', 'recovery_decision', ['customer_id', 'channel', 'evaluated_at'], unique=False)
    op.create_index('ix_recovery_decision_outcome_reason', 'recovery_decision', ['outcome', 'reason_code', 'evaluated_at'], unique=False)
    op.add_column('send_schedule', sa.Column('recovery_decision_id', sa.String(length=64), nullable=True))
    op.add_column('send_schedule', sa.Column('policy_version', sa.String(length=64), nullable=True))
    op.add_column('send_schedule', sa.Column('policy_configuration_hash', sa.String(length=64), nullable=True))
    op.execute("""
        UPDATE send_schedule
        SET policy_version = 'phase3-generator-unversioned',
            policy_configuration_hash = repeat('0', 64)
    """)
    op.alter_column('send_schedule', 'policy_version', nullable=False)
    op.alter_column('send_schedule', 'policy_configuration_hash', nullable=False)
    op.create_foreign_key('fk_send_schedule_recovery_decision', 'send_schedule', 'recovery_decision', ['recovery_decision_id'], ['business_id'])
    op.execute(
        'CREATE TRIGGER trg_recovery_decision_immutable_business_id '
        'BEFORE UPDATE OF business_id ON public.recovery_decision '
        'FOR EACH ROW EXECUTE FUNCTION public.prevent_business_id_change()'
    )
    op.execute(
        'CREATE TRIGGER trg_recovery_decision_append_only '
        'BEFORE UPDATE OR DELETE ON public.recovery_decision '
        'FOR EACH ROW EXECUTE FUNCTION public.prevent_row_mutation()'
    )


def downgrade() -> None:
    op.execute('DROP TRIGGER trg_recovery_decision_append_only ON public.recovery_decision')
    op.execute('DROP TRIGGER trg_recovery_decision_immutable_business_id ON public.recovery_decision')
    op.drop_constraint('fk_send_schedule_recovery_decision', 'send_schedule', type_='foreignkey')
    op.drop_column('send_schedule', 'policy_configuration_hash')
    op.drop_column('send_schedule', 'policy_version')
    op.drop_column('send_schedule', 'recovery_decision_id')
    op.drop_index('ix_recovery_decision_outcome_reason', table_name='recovery_decision')
    op.drop_index('ix_recovery_decision_customer_channel_evaluated', table_name='recovery_decision')
    op.drop_index('ix_recovery_decision_cart_evaluated', table_name='recovery_decision')
    op.drop_table('recovery_decision')