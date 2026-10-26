from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class RecoveryDecision(Base):
    __tablename__ = "recovery_decision"
    __table_args__ = (
        CheckConstraint(
            "decision_type IN ('abandonment', 'eligibility')",
            name="decision_type_valid",
        ),
        CheckConstraint("outcome IN ('eligible', 'suppressed')", name="outcome_valid"),
        CheckConstraint("length(channel) > 0", name="channel_not_empty"),
        CheckConstraint("length(policy_version) > 0", name="policy_version_not_empty"),
        CheckConstraint("length(configuration_hash) = 64", name="configuration_hash_length"),
        Index("ix_recovery_decision_cart_evaluated", "cart_id", "evaluated_at"),
        Index("ix_recovery_decision_customer_channel_evaluated", "customer_id", "channel", "evaluated_at"),
        Index("ix_recovery_decision_outcome_reason", "outcome", "reason_code", "evaluated_at"),
    )

    business_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    decision_type: Mapped[str] = mapped_column(String(20), nullable=False)
    cart_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("cart.business_id", name="fk_recovery_decision_cart"), nullable=False
    )
    customer_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("customer.business_id", name="fk_recovery_decision_customer"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    campaign_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("campaign.business_id", name="fk_recovery_decision_campaign")
    )
    template_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("message_template.business_id", name="fk_recovery_decision_template")
    )
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(64))
    evaluated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    evidence: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)

    cart: Mapped[Cart] = relationship()
    customer: Mapped[Customer] = relationship()
    campaign: Mapped[Campaign | None] = relationship()
    template: Mapped[MessageTemplate | None] = relationship()