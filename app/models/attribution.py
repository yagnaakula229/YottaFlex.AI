from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class AttributionDecision(Base):
    __tablename__ = "attribution_decision"
    __table_args__ = (Index("ix_attribution_decision_order_decided", "order_id", "decided_at"),)

    business_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("orders.business_id", name="fk_attribution_decision_order"), nullable=False
    )
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(32), nullable=False)
    decided_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    details: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)

    order: Mapped[Order] = relationship(back_populates="attribution_decisions")
    candidates: Mapped[list[AttributionCandidate]] = relationship(back_populates="decision")


class AttributionCandidate(Base):
    __tablename__ = "attribution_candidate"
    __table_args__ = (
        UniqueConstraint("decision_id", "rank", name="uq_attribution_candidate_decision_rank"),
        UniqueConstraint("decision_id", "message_event_id", name="uq_attribution_candidate_decision_event"),
        CheckConstraint("rank > 0", name="rank_positive"),
        Index("ix_attribution_candidate_evaluation", "decision_id", "eligible", "rank"),
        Index("ix_attribution_candidate_campaign", "campaign_id", "eligible"),
    )

    business_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    decision_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("attribution_decision.business_id", name="fk_attribution_candidate_decision"),
        nullable=False,
    )
    campaign_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("campaign.business_id", name="fk_attribution_candidate_campaign"), nullable=False
    )
    message_event_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("message_event.business_id", name="fk_attribution_candidate_message_event"),
        nullable=False,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    eligible: Mapped[bool] = mapped_column(Boolean, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255))

    decision: Mapped[AttributionDecision] = relationship(back_populates="candidates")
    campaign: Mapped[Campaign] = relationship("Campaign")
    message_event: Mapped[MessageEvent] = relationship("MessageEvent")


class Attribution(Base):
    __tablename__ = "attribution"
    __table_args__ = (
        UniqueConstraint("order_id", name="uq_attribution_order_canonical"),
        CheckConstraint("credited_amount IS NULL OR credited_amount >= 0", name="credited_amount_nonnegative"),
        CheckConstraint(
            "currency_code IS NULL OR currency_code ~ '^[A-Z]{3}$'",
            name="currency_code_valid",
        ),
        Index("ix_attribution_campaign", "campaign_id", "created_at"),
    )

    business_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    order_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("orders.business_id", name="fk_attribution_order"), nullable=False
    )
    decision_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("attribution_decision.business_id", name="fk_attribution_decision")
    )
    campaign_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("campaign.business_id", name="fk_attribution_campaign")
    )
    message_event_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("message_event.business_id", name="fk_attribution_message_event")
    )
    credited_amount: Mapped[Decimal | None] = mapped_column(Numeric(19, 4))
    currency_code: Mapped[str | None] = mapped_column(CHAR(3))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    order: Mapped[Order] = relationship(back_populates="attribution")
    campaign: Mapped[Campaign | None] = relationship()