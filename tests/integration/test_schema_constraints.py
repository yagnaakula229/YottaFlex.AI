from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, inspect, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.engine import make_url

from app.core.config import get_settings
from app.db.base import Base
from app.evaluation.base import EvaluationBase
import app.evaluation.models
from app.evaluation.models import EvaluationRun, GroundTruthLabel
from app.models import (
    Attribution,
    Campaign,
    Cart,
    CartLine,
    Consent,
    ConsentEvent,
    Customer,
    Order,
    SendSchedule,
)

pytestmark = pytest.mark.integration
FIXED_TIME = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)


@pytest.fixture
def db_session():
    settings = get_settings()
    if not settings.test_database_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")

    if not (make_url(settings.test_database_url).database or "").endswith("_test"):
        pytest.fail("TEST_DATABASE_URL must target a dedicated database ending in _test")
    engine = create_engine(settings.test_database_url, pool_pre_ping=True)
    if not inspect(engine).has_table("customer"):
        engine.dispose()
        pytest.fail("Run `python -m alembic upgrade head` against TEST_DATABASE_URL first")

    tables = [*Base.metadata.tables.values(), *EvaluationBase.metadata.tables.values()]
    qualified_tables = ", ".join(f'"{table.schema or "public"}"."{table.name}"' for table in tables)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {qualified_tables} CASCADE"))

    with engine.connect() as connection:
        transaction = connection.begin()
        session = Session(bind=connection, expire_on_commit=False)
        try:
            yield session
        finally:
            session.close()
            transaction.rollback()
    engine.dispose()


def add_dependencies(session: Session) -> tuple[Customer, Campaign, Cart, Order]:
    customer = Customer(business_id="CUS-000001", status="active", created_at=FIXED_TIME)
    campaign = Campaign(business_id="CMP-2026-000001", name="Test", status="draft", created_at=FIXED_TIME)
    cart = Cart(
        business_id="CART-2026-000001",
        customer_id=customer.business_id,
        status="open",
        total_amount=Decimal("10.0000"),
        currency_code="USD",
        created_at=FIXED_TIME,
        updated_at=FIXED_TIME,
    )
    order = Order(
        business_id="ORD-2026-000001",
        customer_id=customer.business_id,
        cart_id=cart.business_id,
        status="paid",
        total_amount=Decimal("10.0000"),
        currency_code="USD",
        placed_at=FIXED_TIME,
    )
    session.add_all([customer, campaign, cart, order])
    session.flush()
    return customer, campaign, cart, order


def test_metadata_isolated_and_supplied_ids_are_representable(db_session: Session) -> None:
    customer, campaign, cart, order = add_dependencies(db_session)

    assert customer.business_id == "CUS-000001"
    assert campaign.business_id == "CMP-2026-000001"
    assert cart.business_id == "CART-2026-000001"
    assert order.business_id == "ORD-2026-000001"
    assert len("MSG--01") <= 64
    assert "evaluation.evaluation_run" not in Base.metadata.tables
    assert "evaluation.ground_truth_label" not in Base.metadata.tables
    assert set(EvaluationBase.metadata.tables) == {
        "evaluation.evaluation_run",
        "evaluation.ground_truth_label",
    }


def test_required_customer_fields_are_enforced_by_postgresql(db_session: Session) -> None:
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(Customer(business_id="CUS-MISSING-REQUIRED"))
            db_session.flush()


def test_duplicate_business_id_is_rejected(db_session: Session) -> None:
    add_dependencies(db_session)

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(
                Customer(business_id="CUS-000001", status="active", created_at=FIXED_TIME)
            )
            db_session.flush()


def test_consent_is_unique_per_customer_channel_but_history_is_preserved(
    db_session: Session,
) -> None:
    customer, _, _, _ = add_dependencies(db_session)
    db_session.add(
        Consent(
            business_id="CONSENT-1",
            customer_id=customer.business_id,
            channel="email",
            state="granted",
            updated_at=FIXED_TIME,
        )
    )
    db_session.flush()

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(
                Consent(
                    business_id="CONSENT-2",
                    customer_id=customer.business_id,
                    channel="email",
                    state="denied",
                    updated_at=FIXED_TIME,
                )
            )
            db_session.flush()

    db_session.add_all(
        [
            ConsentEvent(
                business_id=f"CONSENT-EVENT-{event_number}",
                customer_id=customer.business_id,
                channel="email",
                event_type=event_type,
                state=state,
                source_system="test",
                source_event_key=f"consent-{event_number}",
                occurred_at=FIXED_TIME,
                recorded_at=FIXED_TIME,
            )
            for event_number, event_type, state in (
                (1, "consent_granted", "granted"),
                (2, "consent_revoked", "denied"),
            )
        ]
    )
    db_session.flush()

    history = db_session.scalars(
        select(ConsentEvent).where(
            ConsentEvent.customer_id == customer.business_id,
            ConsentEvent.channel == "email",
        )
    ).all()
    assert len(history) == 2


def test_invalid_foreign_key_is_rejected(db_session: Session) -> None:
    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(
                Cart(
                    business_id="CART-INVALID-CUSTOMER",
                    customer_id="CUS-DOES-NOT-EXIST",
                    status="open",
                    total_amount=Decimal("1.0000"),
                    currency_code="USD",
                    created_at=FIXED_TIME,
                    updated_at=FIXED_TIME,
                )
            )
            db_session.flush()


def test_cart_line_quantity_must_be_positive(db_session: Session) -> None:
    _, _, cart, _ = add_dependencies(db_session)

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(
                CartLine(
                    business_id="LINE-INVALID-QUANTITY",
                    cart_id=cart.business_id,
                    item_key="SKU-1",
                    quantity=0,
                    unit_price=Decimal("1.0000"),
                    line_total=Decimal("0.0000"),
                    currency_code="USD",
                    attributes={},
                )
            )
            db_session.flush()


def test_schedule_idempotency_key_is_unique(db_session: Session) -> None:
    _, campaign, cart, _ = add_dependencies(db_session)
    first = SendSchedule(
        business_id="SEND-2026-000001",
        idempotency_key="schedule-key-1",
        request_fingerprint="a" * 64,
        customer_id="CUS-000001",
        cart_id=cart.business_id,
        campaign_id=campaign.business_id,
        recovery_decision_id=None,
        channel="email",
        policy_version="test-v1",
        policy_configuration_hash="b" * 64,
        status="scheduled",
        scheduled_for=FIXED_TIME,
        created_at=FIXED_TIME,
    )
    db_session.add(first)
    db_session.flush()

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(
                SendSchedule(
                    business_id="SEND-2026-000002",
                    idempotency_key="schedule-key-1",
                    request_fingerprint="a" * 64,
                    customer_id="CUS-000001",
                    cart_id=cart.business_id,
                    campaign_id=campaign.business_id,
                    recovery_decision_id=None,
                    channel="email",
                    policy_version="test-v1",
                    policy_configuration_hash="b" * 64,
                    status="scheduled",
                    scheduled_for=FIXED_TIME,
                    created_at=FIXED_TIME,
                )
            )
            db_session.flush()


def test_order_has_at_most_one_canonical_attribution(db_session: Session) -> None:
    _, _, _, order = add_dependencies(db_session)
    db_session.add(
        Attribution(
            business_id="ATTR-1",
            order_id=order.business_id,
            credited_amount=Decimal("10.0000"),
            currency_code="USD",
            created_at=FIXED_TIME,
        )
    )
    db_session.flush()

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.add(
                Attribution(
                    business_id="ATTR-2",
                    order_id=order.business_id,
                    credited_amount=Decimal("10.0000"),
                    currency_code="USD",
                    created_at=FIXED_TIME,
                )
            )
            db_session.flush()


def test_business_id_cannot_be_updated(db_session: Session) -> None:
    add_dependencies(db_session)

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                update(Customer)
                .where(Customer.business_id == "CUS-000001")
                .values(business_id="CUS-CHANGED")
            )


def test_operational_event_history_is_append_only(db_session: Session) -> None:
    customer, _, _, _ = add_dependencies(db_session)
    consent_event = ConsentEvent(
        business_id="CONSENT-EVENT-1",
        customer_id=customer.business_id,
        channel="email",
        event_type="consent_granted",
        state="granted",
        source_system="test",
        source_event_key="event-1",
        occurred_at=FIXED_TIME,
        recorded_at=FIXED_TIME,
    )
    db_session.add(consent_event)
    db_session.flush()

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                update(ConsentEvent)
                .where(ConsentEvent.business_id == consent_event.business_id)
                .values(state="denied")
            )


def test_ground_truth_labels_are_separate_and_append_only(db_session: Session) -> None:
    evaluation_run = EvaluationRun(
        business_id="EVAL-RUN-1",
        status="completed",
        started_at=FIXED_TIME,
        finished_at=FIXED_TIME,
        results={},
    )
    label = GroundTruthLabel(
        business_id="LABEL-1",
        evaluation_run_id=evaluation_run.business_id,
        label_code="message_sent_after_opt_out",
        entity_type="send_schedule",
        entity_business_id="SEND-2026-000001",
        expected=True,
        label_payload={},
        recorded_at=FIXED_TIME,
    )
    db_session.add_all([evaluation_run, label])
    db_session.flush()

    with pytest.raises(IntegrityError):
        with db_session.begin_nested():
            db_session.execute(
                update(GroundTruthLabel)
                .where(GroundTruthLabel.business_id == label.business_id)
                .values(expected=False)
            )