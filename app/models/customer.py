from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Customer(Base):
    __tablename__ = "customer"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'suppressed', 'deleted')", name="status_valid"),
        Index("ix_customer_status", "status"),
    )

    business_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str | None] = mapped_column(String(320))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    consents: Mapped[list[Consent]] = relationship(back_populates="customer")
    sessions: Mapped[list[CustomerSession]] = relationship(back_populates="customer")
    carts: Mapped[list[Cart]] = relationship(back_populates="customer")
    orders: Mapped[list[Order]] = relationship(back_populates="customer")


class Consent(Base):
    __tablename__ = "consent"
    __table_args__ = (
        UniqueConstraint("customer_id", "channel", name="uq_consent_customer_channel"),
        CheckConstraint("state IN ('unknown', 'granted', 'denied')", name="state_valid"),
        CheckConstraint("length(channel) > 0", name="channel_not_empty"),
        Index("ix_consent_channel_state", "channel", "state"),
    )

    business_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("customer.business_id", name="fk_consent_customer"), nullable=False
    )
    last_event_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("consent_event.business_id", name="fk_consent_last_event")
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    customer: Mapped[Customer] = relationship(back_populates="consents")
    last_event: Mapped[ConsentEvent | None] = relationship(foreign_keys=[last_event_id])


class ConsentEvent(Base):
    __tablename__ = "consent_event"
    __table_args__ = (
        CheckConstraint("state IN ('unknown', 'granted', 'denied')", name="state_valid"),
        CheckConstraint("length(channel) > 0", name="channel_not_empty"),
        UniqueConstraint("source_system", "source_event_key", name="uq_consent_event_source_key"),
        Index("ix_consent_event_customer_channel_occurred", "customer_id", "channel", "occurred_at"),
    )

    business_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("customer.business_id", name="fk_consent_event_customer"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    event_type: Mapped[str] = mapped_column(String(40), nullable=False)
    state: Mapped[str] = mapped_column(String(16), nullable=False)
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    source_event_key: Mapped[str] = mapped_column(String(255), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    customer: Mapped[Customer] = relationship()