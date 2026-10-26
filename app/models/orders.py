from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from sqlalchemy import CHAR, CheckConstraint, DateTime, ForeignKey, Index, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        CheckConstraint("status IN ('pending', 'paid', 'cancelled', 'refunded')", name="status_valid"),
        CheckConstraint("total_amount >= 0", name="total_nonnegative"),
        CheckConstraint("currency_code ~ '^[A-Z]{3}$'", name="currency_code_valid"),
        Index("ix_orders_customer_placed", "customer_id", "placed_at"),
        Index("ix_orders_cart", "cart_id"),
    )

    business_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    customer_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("customer.business_id", name="fk_orders_customer"), nullable=False
    )
    cart_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("cart.business_id", name="fk_orders_cart")
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Numeric(19, 4), nullable=False)
    currency_code: Mapped[str] = mapped_column(CHAR(3), nullable=False)
    placed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    customer: Mapped[Customer] = relationship(back_populates="orders")
    cart: Mapped[Cart | None] = relationship(back_populates="orders")
    attribution: Mapped[Attribution | None] = relationship(back_populates="order", uselist=False)
    attribution_decisions: Mapped[list[AttributionDecision]] = relationship(back_populates="order")