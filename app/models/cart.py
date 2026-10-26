from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CHAR,
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


class Cart(Base):
    __tablename__ = "cart"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'converted', 'closed', 'abandoned')", name="status_valid"),
        CheckConstraint("total_amount >= 0", name="total_nonnegative"),
        CheckConstraint("currency_code ~ '^[A-Z]{3}$'", name="currency_code_valid"),
        Index("ix_cart_customer_status", "customer_id", "status"),
    )

    business_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("customer.business_id", name="fk_cart_customer"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    currency_code: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    customer: Mapped[Customer] = relationship(back_populates="carts")
    lines: Mapped[list[CartLine]] = relationship(back_populates="cart")
    events: Mapped[list[CartEvent]] = relationship(back_populates="cart")
    schedules: Mapped[list[SendSchedule]] = relationship(back_populates="cart")
    orders: Mapped[list[Order]] = relationship(back_populates="cart")


class CartLine(Base):
    __tablename__ = "cart_line"
    __table_args__ = (
        CheckConstraint("quantity > 0", name="quantity_positive"),
        CheckConstraint("unit_price >= 0", name="unit_price_nonnegative"),
        CheckConstraint("line_total >= 0", name="line_total_nonnegative"),
        CheckConstraint("currency_code ~ '^[A-Z]{3}$'", name="currency_code_valid"),
        UniqueConstraint("cart_id", "item_key", name="uq_cart_line_cart_item"),
        Index("ix_cart_line_cart", "cart_id"),
    )

    business_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    cart_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("cart.business_id", name="fk_cart_line_cart"), nullable=False
    )
    item_key: Mapped[str] = mapped_column(String(128), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    line_total: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    currency_code: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    attributes: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)

    cart: Mapped[Cart] = relationship(back_populates="lines")


class CartEvent(Base):
    __tablename__ = "cart_event"
    __table_args__ = (
        UniqueConstraint("source_system", "source_event_key", name="uq_cart_event_source_key"),
        Index("ix_cart_event_cart_occurred", "cart_id", "occurred_at"),
    )

    business_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    cart_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("cart.business_id", name="fk_cart_event_cart"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    source_system: Mapped[str] = mapped_column(String(64), nullable=False)
    source_event_key: Mapped[str] = mapped_column(String(255), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)

    cart: Mapped[Cart] = relationship(back_populates="events")