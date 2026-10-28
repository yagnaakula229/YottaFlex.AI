from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from app.models import Order
from app.services.recovery.decisions import require_aware
from app.services.recovery.errors import InvalidDecisionInputError

VALID_ORDER_STATUSES = {"pending", "paid", "cancelled", "refunded"}


def _normalize_order_status(value: str) -> str:
    if value is None:
        raise InvalidDecisionInputError("status is required")
    normalized = str(value).strip().lower()
    if normalized not in VALID_ORDER_STATUSES:
        raise InvalidDecisionInputError(
            f"status '{value}' is not valid; allowed values are {sorted(VALID_ORDER_STATUSES)}"
        )
    return normalized


def _normalize_currency_code(value: str) -> str:
    if value is None:
        raise InvalidDecisionInputError("currency_code is required")
    normalized = str(value).strip().upper()
    if len(normalized) != 3 or not normalized.isalpha():
        raise InvalidDecisionInputError("currency_code must be a three-letter ISO currency code")
    return normalized


def _normalize_total_amount(value: Decimal | int | float | str) -> Decimal:
    if value is None:
        raise InvalidDecisionInputError("total_amount is required")
    if isinstance(value, bool) or not isinstance(value, (Decimal, int, float, str)):
        raise InvalidDecisionInputError("total_amount must be numeric")
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise InvalidDecisionInputError("total_amount must be numeric") from exc
    if not amount.is_finite():
        raise InvalidDecisionInputError("total_amount must be a finite numeric value")
    if amount < 0:
        raise InvalidDecisionInputError("total_amount must be non-negative")
    return amount


def record_order(
    session: Session,
    *,
    business_id: str,
    customer_id: str,
    status: str,
    total_amount: Decimal | int | float | str,
    currency_code: str,
    placed_at: datetime,
    cart_id: str | None = None,
) -> Order:
    if not business_id or not str(business_id).strip():
        raise InvalidDecisionInputError("business_id is required")
    if not customer_id or not str(customer_id).strip():
        raise InvalidDecisionInputError("customer_id is required")
    if cart_id is not None and not str(cart_id).strip():
        raise InvalidDecisionInputError("cart_id cannot be blank when provided")

    require_aware(placed_at, "placed_at")

    order = Order(
        business_id=str(business_id).strip(),
        customer_id=str(customer_id).strip(),
        cart_id=str(cart_id).strip() if cart_id is not None else None,
        status=_normalize_order_status(status),
        total_amount=_normalize_total_amount(total_amount),
        currency_code=_normalize_currency_code(currency_code),
        placed_at=placed_at.astimezone(UTC),
    )
    session.add(order)
    session.flush([order])
    return order


def record_synthetic_order(
    session: Session,
    *,
    business_id: str,
    customer_id: str,
    status: str,
    total_amount: Decimal | int | float | str,
    currency_code: str,
    placed_at: datetime,
    cart_id: str | None = None,
) -> Order:
    return record_order(
        session,
        business_id=business_id,
        customer_id=customer_id,
        status=status,
        total_amount=total_amount,
        currency_code=currency_code,
        placed_at=placed_at,
        cart_id=cart_id,
    )
