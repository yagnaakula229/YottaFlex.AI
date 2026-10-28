from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.services.orders.service import record_order
from app.services.recovery.errors import InvalidDecisionInputError


@pytest.mark.unit
def test_record_order_accepts_valid_values_and_allows_null_cart_id() -> None:
    session = _FakeSession()

    order = record_order(
        session,
        business_id="ORD-001",
        customer_id="CUST-001",
        cart_id=None,
        status="paid",
        total_amount=Decimal("42.50"),
        currency_code="USD",
        placed_at=datetime(2026, 10, 22, 12, 0, tzinfo=UTC),
    )

    assert order.business_id == "ORD-001"
    assert order.customer_id == "CUST-001"
    assert order.cart_id is None
    assert order.status == "paid"
    assert order.total_amount == Decimal("42.50")
    assert order.currency_code == "USD"
    assert order.placed_at == datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
    assert session.added == [order]


@pytest.mark.unit
def test_record_order_rejects_negative_total_amount() -> None:
    with pytest.raises(InvalidDecisionInputError):
        record_order(
            _FakeSession(),
            business_id="ORD-NEG",
            customer_id="CUST-001",
            status="paid",
            total_amount=Decimal("-1.00"),
            currency_code="USD",
            placed_at=datetime(2026, 10, 22, 12, 0, tzinfo=UTC),
        )


@pytest.mark.parametrize(
    "amount",
    [
        Decimal("NaN"),
        Decimal("Infinity"),
        Decimal("-Infinity"),
        float("nan"),
        float("inf"),
        float("-inf"),
        "NaN",
        "Infinity",
        "-Infinity",
        "not-a-number",
        object(),
    ],
)
@pytest.mark.unit
def test_record_order_rejects_non_finite_and_malformed_amounts(amount) -> None:
    session = _FakeSession()

    with pytest.raises(InvalidDecisionInputError):
        record_order(
            session,
            business_id="ORD-BAD-AMOUNT",
            customer_id="CUST-001",
            status="paid",
            total_amount=amount,
            currency_code="USD",
            placed_at=datetime(2026, 10, 22, 12, 0, tzinfo=UTC),
        )

    assert session.add_called is False
    assert session.flush_called is False


@pytest.mark.unit
def test_record_order_rejects_invalid_currency_or_timezone() -> None:
    with pytest.raises(InvalidDecisionInputError):
        record_order(
            _FakeSession(),
            business_id="ORD-BAD-CUR",
            customer_id="CUST-001",
            status="paid",
            total_amount=Decimal("10.00"),
            currency_code="US",
            placed_at=datetime(2026, 10, 22, 12, 0, tzinfo=UTC),
        )

    with pytest.raises(InvalidDecisionInputError):
        record_order(
            _FakeSession(),
            business_id="ORD-NAIVE",
            customer_id="CUST-001",
            status="paid",
            total_amount=Decimal("10.00"),
            currency_code="USD",
            placed_at=datetime(2026, 10, 22, 12, 0),
        )


class _FakeSession:
    def __init__(self) -> None:
        self.added = []
        self.add_called = False
        self.flush_called = False

    def add(self, obj):
        self.add_called = True
        self.added.append(obj)

    def flush(self, *args, **kwargs):
        self.flush_called = True
        return None
