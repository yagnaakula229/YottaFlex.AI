from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class SendSchedule(Base):
    __tablename__ = "send_schedule"
    __table_args__ = (
        UniqueConstraint("idempotency_key", name="uq_send_schedule_idempotency_key"),
        CheckConstraint("length(request_fingerprint) = 64", name="request_fingerprint_length"),
        CheckConstraint(
            "status IN ('scheduled', 'processing', 'sent', 'suppressed', 'cancelled', 'failed')",
            name="status_valid",
        ),
        CheckConstraint("length(channel) > 0", name="channel_not_empty"),
        CheckConstraint("length(policy_version) > 0", name="policy_version_not_empty"),
        CheckConstraint("length(policy_configuration_hash) = 64", name="policy_hash_length"),
        Index("ix_send_schedule_due", "status", "scheduled_for"),
        Index("ix_send_schedule_customer_channel", "customer_id", "channel", "scheduled_for"),
        Index("ix_send_schedule_recovery_decision", "recovery_decision_id"),
    )

    business_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    idempotency_key: Mapped[str] = mapped_column(String(255), nullable=False)
    request_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    customer_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("customer.business_id", name="fk_send_schedule_customer"), nullable=False
    )
    cart_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("cart.business_id", name="fk_send_schedule_cart"), nullable=False
    )
    campaign_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("campaign.business_id", name="fk_send_schedule_campaign"), nullable=False
    )
    recovery_decision_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("recovery_decision.business_id", name="fk_send_schedule_recovery_decision")
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)
    policy_configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    scheduled_for: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    cart: Mapped[Cart] = relationship(back_populates="schedules")
    customer: Mapped[Customer] = relationship()
    campaign: Mapped[Campaign] = relationship(back_populates="schedules")
    recovery_decision: Mapped[RecoveryDecision | None] = relationship()
    attempts: Mapped[list[SendAttempt]] = relationship(back_populates="schedule")


class SendAttempt(Base):
    __tablename__ = "send_attempt"
    __table_args__ = (
        UniqueConstraint("schedule_id", "attempt_number", name="uq_send_attempt_schedule_number"),
        CheckConstraint("attempt_number > 0", name="attempt_number_positive"),
        CheckConstraint("status IN ('started', 'accepted', 'failed')", name="status_valid"),
        Index("ix_send_attempt_schedule_attempted", "schedule_id", "attempted_at"),
    )

    business_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    schedule_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("send_schedule.business_id", name="fk_send_attempt_schedule"), nullable=False
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    attempted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    provider_reference: Mapped[str | None] = mapped_column(String(255))
    error_detail: Mapped[str | None] = mapped_column(String)

    schedule: Mapped[SendSchedule] = relationship(back_populates="attempts")
    events: Mapped[list[MessageEvent]] = relationship(back_populates="send_attempt")


class MessageEvent(Base):
    __tablename__ = "message_event"
    __table_args__ = (
        UniqueConstraint("source_system", "source_event_key", name="uq_message_event_source_key"),
        Index("ix_message_event_attempt_type_occurred", "send_attempt_id", "event_type", "occurred_at"),
        Index("ix_message_event_engagement", "event_type", "occurred_at"),
    )

    business_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    send_attempt_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("send_attempt.business_id", name="fk_message_event_send_attempt"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    source_event_key: Mapped[str] = mapped_column(String(255), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)

    send_attempt: Mapped[SendAttempt] = relationship(back_populates="events")