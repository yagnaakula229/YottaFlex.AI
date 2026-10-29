from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import create_engine, func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.base import Base
from app.evaluation.base import EvaluationBase
from app.evaluation.anomaly_fixtures import detect_attribution_fixture_anomalies
from app.evaluation.models import EvaluationRun, GroundTruthLabel
from app.generation.config import GenerationConfig
from app.generation.pipeline import generate_dataset
from app.models import (
    Attribution,
    Campaign,
    Cart,
    CartEvent,
    CartLine,
    Consent,
    ConsentEvent,
    Customer,
    MessageEvent,
    MessageTemplate,
    Order,
    RecoveryDecision,
    SendAttempt,
    SendSchedule,
)
from app.services.execution.dispatch import dispatch_schedule_attempt
from app.services.attribution.service import evaluate_order_attribution
from app.services.recovery.abandonment import evaluate_cart_abandonment
from app.services.recovery.consent import record_consent_change, resolve_effective_consent
from app.services.recovery.eligibility import (
    evaluate_customer_channel_eligibility,
    evaluate_frequency_caps,
    select_campaign_template,
)
from app.services.recovery.errors import IdempotencyConflictError
from app.services.recovery.policy import RecoveryPolicy
from app.services.recovery.scheduling import create_logical_schedule, schedule_idempotency_key
from app.services.validation.anomalies import detect_operational_anomalies

pytestmark = pytest.mark.integration
REFERENCE_TIME = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
EVALUATION_TIME = REFERENCE_TIME + timedelta(days=30)


@pytest.fixture
def generated_small_db():
    settings = get_settings()
    if not settings.test_database_url:
        pytest.skip("Set TEST_DATABASE_URL to run PostgreSQL integration tests")
    if not (make_url(settings.test_database_url).database or "").endswith("_test"):
        pytest.fail("Recovery integration tests require a dedicated database ending in _test")

    engine = create_engine(settings.test_database_url, pool_pre_ping=True)
    tables = [*Base.metadata.tables.values(), *EvaluationBase.metadata.tables.values()]
    qualified_tables = ", ".join(f'"{table.schema or "public"}"."{table.name}"' for table in tables)
    with engine.begin() as connection:
        connection.execute(text(f"TRUNCATE TABLE {qualified_tables} CASCADE"))
    with Session(engine) as session, session.begin():
        generate_dataset(
            session,
            GenerationConfig(profile="small", reference_time=REFERENCE_TIME),
        )

    yield engine
    engine.dispose()


def select_eligible_email_cart(session: Session) -> Cart:
    cart = session.scalar(
        select(Cart)
        .join(Consent, Consent.customer_id == Cart.customer_id)
        .where(
            Cart.status == "abandoned",
            Consent.channel == "email",
            Consent.state == "granted",
        )
        .order_by(Cart.business_id)
        .limit(1)
    )
    assert cart is not None
    return cart


def test_abandonment_threshold_is_inclusive_and_decisions_are_append_only(generated_small_db) -> None:
    policy = RecoveryPolicy()
    with Session(generated_small_db) as session, session.begin():
        cart = select_eligible_email_cart(session)
        at_boundary = cart.updated_at + policy.inactivity_threshold
        before_boundary = at_boundary - timedelta(microseconds=1)

        early = evaluate_cart_abandonment(
            session,
            cart_id=cart.business_id,
            evaluated_at=before_boundary,
            policy=policy,
        )
        boundary = evaluate_cart_abandonment(
            session,
            cart_id=cart.business_id,
            evaluated_at=at_boundary,
            policy=policy,
        )

        assert early.eligible is False
        assert early.reason_code == "cart_not_inactive_long_enough"
        assert boundary.eligible is True
        assert boundary.decision.evaluated_at == at_boundary
        assert boundary.decision.policy_version == policy.version
        assert boundary.decision.configuration_hash == policy.configuration_hash
        decisions = session.scalars(
            select(RecoveryDecision)
            .where(RecoveryDecision.cart_id == cart.business_id)
            .order_by(RecoveryDecision.evaluated_at, RecoveryDecision.business_id)
        ).all()
        assert len(decisions) == 2
        assert decisions[0].business_id != decisions[1].business_id

        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.execute(
                    update(RecoveryDecision)
                    .where(RecoveryDecision.business_id == boundary.decision.business_id)
                    .values(reason_code="silently_rewritten")
                )


def test_empty_cart_stale_total_and_prior_purchase_have_explicit_reasons(generated_small_db) -> None:
    with Session(generated_small_db) as session, session.begin():
        cart = select_eligible_email_cart(session)
        empty_cart_id = "CART-PHASE4-EMPTY"
        session.add(
            Cart(
                business_id=empty_cart_id,
                customer_id=cart.customer_id,
                status="open",
                total_amount=Decimal("0.0000"),
                currency_code="USD",
                created_at=REFERENCE_TIME,
                updated_at=REFERENCE_TIME,
            )
        )
        session.flush()
        empty = evaluate_cart_abandonment(
            session,
            cart_id=empty_cart_id,
            evaluated_at=EVALUATION_TIME,
        )
        assert empty.eligible is False
        assert empty.reason_code == "empty_cart"

        stale_line = session.scalar(
            select(CartLine).where(CartLine.cart_id == cart.business_id).order_by(CartLine.business_id).limit(1)
        )
        assert stale_line is not None
        stale_line.line_total += Decimal("1.0000")
        stale = evaluate_cart_abandonment(
            session,
            cart_id=cart.business_id,
            evaluated_at=EVALUATION_TIME,
        )
        assert stale.eligible is False
        assert stale.reason_code == "stale_cart_line_total"
        stale_line.line_total -= Decimal("1.0000")
        cart.total_amount += Decimal("1.0000")
        stale_cart = evaluate_cart_abandonment(
            session,
            cart_id=cart.business_id,
            evaluated_at=EVALUATION_TIME,
        )
        assert stale_cart.eligible is False
        assert stale_cart.reason_code == "stale_cart_total"

        purchased_cart = session.scalar(
            select(Cart)
            .join(Order, Order.cart_id == Cart.business_id)
            .order_by(Cart.business_id)
            .limit(1)
        )
        assert purchased_cart is not None
        prior_purchase = evaluate_cart_abandonment(
            session,
            cart_id=purchased_cart.business_id,
            evaluated_at=EVALUATION_TIME,
        )
        assert prior_purchase.eligible is False
        assert prior_purchase.reason_code == "prior_purchase"


def test_customer_suppression_and_missing_campaigns_are_explicit(generated_small_db) -> None:
    with Session(generated_small_db) as session, session.begin():
        cart = select_eligible_email_cart(session)
        customer = session.get(Customer, cart.customer_id)
        assert customer is not None
        customer.status = "suppressed"
        customer_suppressed = evaluate_customer_channel_eligibility(
            session,
            cart_id=cart.business_id,
            channel="email",
            evaluated_at=EVALUATION_TIME,
        )
        assert customer_suppressed.eligible is False
        assert customer_suppressed.reason_code == "customer_inactive"

        customer.status = "active"
        session.execute(update(Campaign).values(status="paused"))
        no_campaign = evaluate_customer_channel_eligibility(
            session,
            cart_id=cart.business_id,
            channel="email",
            evaluated_at=EVALUATION_TIME,
        )
        assert no_campaign.eligible is False
        assert no_campaign.reason_code == "NO_CAMPAIGN_TEMPLATE"


def test_consent_history_is_channel_specific_and_withdrawal_blocks(generated_small_db) -> None:
    with Session(generated_small_db) as session, session.begin():
        cart = select_eligible_email_cart(session)
        customer_id = cart.customer_id
        granted_at = EVALUATION_TIME - timedelta(hours=3)
        denied_at = EVALUATION_TIME - timedelta(hours=2)
        withdraw_at = EVALUATION_TIME - timedelta(hours=1)

        record_consent_change(
            session,
            customer_id=customer_id,
            channel="email",
            state="granted",
            event_type="consent_updated",
            source_system="phase4-test",
            source_event_key="email-granted",
            occurred_at=granted_at,
            recorded_at=granted_at,
        )
        record_consent_change(
            session,
            customer_id=customer_id,
            channel="sms",
            state="denied",
            event_type="consent_updated",
            source_system="phase4-test",
            source_event_key="sms-denied",
            occurred_at=denied_at,
            recorded_at=denied_at,
        )
        withdrawal_event = record_consent_change(
            session,
            customer_id=customer_id,
            channel="email",
            state="granted",
            event_type="unsubscribe",
            source_system="phase4-test",
            source_event_key="email-withdrawn",
            occurred_at=withdraw_at,
            recorded_at=withdraw_at,
        )
        record_consent_change(
            session,
            customer_id=customer_id,
            channel="email",
            state="granted",
            event_type="consent_updated",
            source_system="phase4-test",
            source_event_key="late-email-grant",
            occurred_at=granted_at - timedelta(days=1),
            recorded_at=EVALUATION_TIME,
        )

        email = resolve_effective_consent(
            session, customer_id=customer_id, channel="email", at=EVALUATION_TIME
        )
        sms = resolve_effective_consent(
            session, customer_id=customer_id, channel="sms", at=EVALUATION_TIME
        )
        future = resolve_effective_consent(
            session,
            customer_id=customer_id,
            channel="email",
            at=EVALUATION_TIME - timedelta(hours=2, minutes=30),
        )

        assert email.allowed is False
        assert email.reason_code == "consent_withdrawn"
        assert sms.allowed is False
        assert sms.reason_code == "consent_not_granted"
        assert future.allowed is True
        projection = session.scalar(
            select(Consent).where(Consent.customer_id == customer_id, Consent.channel == "email")
        )
        assert projection is not None and projection.state == "denied"
        assert projection.last_event_id == withdrawal_event.business_id
        event_count = session.scalar(
            select(func.count(ConsentEvent.business_id)).where(
                ConsentEvent.customer_id == customer_id,
                ConsentEvent.source_system == "phase4-test",
            )
        )
        assert event_count == 4


def test_frequency_caps_use_accepted_attempts_and_open_left_closed_right_windows(generated_small_db) -> None:
    with Session(generated_small_db) as session, session.begin():
        cart = select_eligible_email_cart(session)
        schedule = session.scalar(
            select(SendSchedule)
            .where(SendSchedule.customer_id == cart.customer_id, SendSchedule.channel == "email")
            .order_by(SendSchedule.business_id)
            .limit(1)
        )
        assert schedule is not None
        lower = EVALUATION_TIME - timedelta(hours=24)
        session.add_all(
            [
                SendAttempt(
                    business_id="SATT-PHASE4-LOWER",
                    schedule_id=schedule.business_id,
                    attempt_number=2,
                    status="accepted",
                    attempted_at=lower,
                ),
                SendAttempt(
                    business_id="SATT-PHASE4-UPPER",
                    schedule_id=schedule.business_id,
                    attempt_number=3,
                    status="accepted",
                    attempted_at=EVALUATION_TIME,
                ),
                SendAttempt(
                    business_id="SATT-PHASE4-FAILED",
                    schedule_id=schedule.business_id,
                    attempt_number=4,
                    status="failed",
                    attempted_at=EVALUATION_TIME - timedelta(hours=1),
                ),
                SendAttempt(
                    business_id="SATT-PHASE4-7D-LOWER",
                    schedule_id=schedule.business_id,
                    attempt_number=5,
                    status="accepted",
                    attempted_at=EVALUATION_TIME - timedelta(days=7),
                ),
            ]
        )
        session.flush()

        cap = evaluate_frequency_caps(
            session,
            customer_id=cart.customer_id,
            channel="email",
            evaluated_at=EVALUATION_TIME,
            policy=RecoveryPolicy(frequency_cap_24h=5, frequency_cap_7d=5),
        )
        blocked = evaluate_frequency_caps(
            session,
            customer_id=cart.customer_id,
            channel="email",
            evaluated_at=EVALUATION_TIME,
            policy=RecoveryPolicy(frequency_cap_24h=1, frequency_cap_7d=5),
        )
        inclusive = evaluate_frequency_caps(
            session,
            customer_id=cart.customer_id,
            channel="email",
            evaluated_at=EVALUATION_TIME,
            policy=RecoveryPolicy(
                frequency_cap_24h=5,
                frequency_cap_7d=5,
                rolling_window_boundary="[lower, upper]",
            ),
        )

        assert cap.count_24h == 1
        assert cap.count_7d == 2
        assert cap.allowed is True
        assert blocked.allowed is False
        assert blocked.reason_code == "FREQUENCY_CAP"
        assert blocked.triggered_window == "24h"
        assert inclusive.count_24h == 2
        assert inclusive.count_7d == 3
        assert inclusive.window_boundary == "[lower, upper]"
        sms_cap = evaluate_frequency_caps(
            session,
            customer_id=cart.customer_id,
            channel="sms",
            evaluated_at=EVALUATION_TIME,
            policy=RecoveryPolicy(frequency_cap_24h=5, frequency_cap_7d=5),
        )
        assert sms_cap.count_24h == 0
        assert sms_cap.count_7d == 0


def test_campaign_selection_is_stable_channel_matched_and_missing_campaigns_are_explicit(
    generated_small_db,
) -> None:
    with Session(generated_small_db) as session, session.begin():
        email = select_campaign_template(session, channel="email", evaluated_at=EVALUATION_TIME)
        sms = select_campaign_template(session, channel="sms", evaluated_at=EVALUATION_TIME)
        assert email is not None and email.campaign_id == "CMP-2026-000001"
        assert email.template_id == "TPL-2026-000001" and email.priority == 0
        assert sms is not None and sms.campaign_id == "CMP-2026-000001"
        assert sms.template_id == "TPL-2026-000002" and sms.priority == 1

        session.execute(update(Campaign).values(status="paused"))
        missing = select_campaign_template(session, channel="email", evaluated_at=EVALUATION_TIME)
        assert missing is None


def test_eligibility_records_missing_consent_and_missing_campaign_suppressions(generated_small_db) -> None:
    with Session(generated_small_db) as session, session.begin():
        cart = select_eligible_email_cart(session)
        missing_consent = evaluate_customer_channel_eligibility(
            session,
            cart_id=cart.business_id,
            channel="push",
            evaluated_at=EVALUATION_TIME,
        )
        assert missing_consent.eligible is False
        assert missing_consent.reason_code == "consent_missing"
        assert missing_consent.decision.outcome == "suppressed"
        assert missing_consent.decision.evidence["consent"]["source"] == "none"

        session.execute(update(Campaign).values(status="paused"))
        missing_campaign = evaluate_customer_channel_eligibility(
            session,
            cart_id=cart.business_id,
            channel="email",
            evaluated_at=EVALUATION_TIME,
        )
        assert missing_campaign.eligible is False
        assert missing_campaign.reason_code == "NO_CAMPAIGN_TEMPLATE"
        assert missing_campaign.decision.outcome == "suppressed"


def test_consent_reason_precedes_frequency_cap_when_both_block(generated_small_db) -> None:
    with Session(generated_small_db) as session, session.begin():
        cart = select_eligible_email_cart(session)
        schedule = session.scalar(
            select(SendSchedule)
            .where(SendSchedule.customer_id == cart.customer_id, SendSchedule.channel == "email")
            .order_by(SendSchedule.business_id)
            .limit(1)
        )
        assert schedule is not None
        session.add(
            SendAttempt(
                business_id="SATT-PHASE4-CAP-CONSENT",
                schedule_id=schedule.business_id,
                attempt_number=2,
                status="accepted",
                attempted_at=EVALUATION_TIME - timedelta(hours=1),
            )
        )
        withdrawn_at = EVALUATION_TIME - timedelta(minutes=30)
        record_consent_change(
            session,
            customer_id=cart.customer_id,
            channel="email",
            state="denied",
            event_type="consent_revoked",
            source_system="phase4-precedence-test",
            source_event_key="withdraw-email",
            occurred_at=withdrawn_at,
            recorded_at=withdrawn_at,
        )
        session.flush()

        result = evaluate_customer_channel_eligibility(
            session,
            cart_id=cart.business_id,
            channel="email",
            evaluated_at=EVALUATION_TIME,
            policy=RecoveryPolicy(frequency_cap_24h=1),
        )

        assert result.eligible is False
        assert result.reason_code == "consent_withdrawn"
        assert result.decision.evidence["consent"]["reason_code"] == "consent_withdrawn"
        assert "frequency_cap" not in result.decision.evidence


def test_dispatch_rechecks_withdrawn_consent_before_creating_attempt(generated_small_db) -> None:
    with Session(generated_small_db) as session, session.begin():
        cart = select_eligible_email_cart(session)
        creation = create_logical_schedule(
            session,
            cart_id=cart.business_id,
            channel="email",
            evaluated_at=EVALUATION_TIME,
        )
        assert creation.eligible and creation.schedule is not None
        schedule = creation.schedule

        withdrawn_at = EVALUATION_TIME + timedelta(minutes=1)
        record_consent_change(
            session,
            customer_id=cart.customer_id,
            channel="email",
            state="denied",
            event_type="consent_revoked",
            source_system="execution-recheck-test",
            source_event_key="execution-recheck-withdrawal",
            occurred_at=withdrawn_at,
            recorded_at=withdrawn_at,
        )

        result = dispatch_schedule_attempt(
            session,
            schedule,
            attempted_at=EVALUATION_TIME + timedelta(minutes=2),
            force_outcome="accepted",
        )

        assert result.eligible is False
        assert result.reason_code == "consent_withdrawn"
        assert result.attempt is None
        assert schedule.status == "suppressed"
        assert session.scalar(
            select(func.count(SendAttempt.business_id)).where(
                SendAttempt.schedule_id == schedule.business_id
            )
        ) == 0


def test_required_anomaly_scenarios_are_detected_and_labels_stay_separate(generated_small_db) -> None:
    with Session(generated_small_db) as session, session.begin():
        evaluation_run = session.scalar(select(EvaluationRun))
        assert evaluation_run is not None

        schedule = session.scalar(select(SendSchedule).order_by(SendSchedule.business_id).limit(1))
        assert schedule is not None
        attempt = session.scalar(
            select(SendAttempt)
            .where(SendAttempt.schedule_id == schedule.business_id)
            .order_by(SendAttempt.attempt_number.desc())
            .limit(1)
        )
        assert attempt is not None
        withdrawal_at = attempt.attempted_at - timedelta(seconds=1)
        withdrawal = record_consent_change(
            session,
            customer_id=schedule.customer_id,
            channel=schedule.channel,
            state="denied",
            event_type="consent_revoked",
            source_system="anomaly-fixture",
            source_event_key="anomaly-withdrawal",
            occurred_at=withdrawal_at,
            recorded_at=withdrawal_at,
        )
        sent_at = attempt.attempted_at
        session.add(
            MessageEvent(
                business_id="ME-ANOMALY-OPT-OUT",
                send_attempt_id=attempt.business_id,
                event_type="sent",
                source_system="anomaly-fixture",
                source_event_key="anomaly-sent-after-withdrawal",
                occurred_at=sent_at,
                recorded_at=sent_at,
                payload={"fixture": "message_sent_after_opt_out"},
            )
        )

        purchased_order = session.scalar(
            select(Order).where(Order.status == "paid").order_by(Order.business_id).limit(1)
        )
        assert purchased_order is not None and purchased_order.cart_id is not None
        abandoned_cart = session.get(Cart, purchased_order.cart_id)
        assert abandoned_cart is not None
        abandoned_at = purchased_order.placed_at + timedelta(hours=1)
        abandoned_cart.status = "abandoned"
        abandoned_cart.updated_at = abandoned_at
        session.add(
            CartEvent(
                business_id="CE-ANOMALY-POST-PURCHASE",
                cart_id=abandoned_cart.business_id,
                event_type="cart_abandoned",
                source_system="anomaly-fixture",
                source_event_key="anomaly-cart-abandoned-after-purchase",
                occurred_at=abandoned_at,
                recorded_at=abandoned_at,
                payload={"fixture": "cart_abandoned_after_purchase"},
            )
        )

        stale_line = session.scalar(
            select(CartLine).order_by(CartLine.business_id).limit(1)
        )
        assert stale_line is not None
        stale_cart = session.get(Cart, stale_line.cart_id)
        assert stale_cart is not None
        stale_cart_id = stale_cart.business_id
        stale_line.quantity += 1

        session.add(
            Attribution(
                business_id="ATTR-ANOMALY-CANONICAL",
                order_id=purchased_order.business_id,
                campaign_id="CMP-2026-000001",
                credited_amount=None,
                currency_code=purchased_order.currency_code,
                created_at=EVALUATION_TIME,
            )
        )
        session.flush()
        evaluation_run.results = {
            **evaluation_run.results,
            "anomaly_fixtures": {
                "attribution_double_counted": [
                    {
                        "order_id": purchased_order.business_id,
                        "credits": [
                            {
                                "attribution_id": "LEGACY-ATTR-CROSS-CAMPAIGN-A",
                                "campaign_id": "CMP-2026-000001",
                            },
                            {
                                "attribution_id": "LEGACY-ATTR-CROSS-CAMPAIGN-B",
                                "campaign_id": "CMP-2026-000002",
                            },
                        ],
                    }
                ]
            },
        }
        with pytest.raises(IntegrityError):
            with session.begin_nested():
                session.add(
                    Attribution(
                        business_id="ATTR-ANOMALY-DUPLICATE",
                        order_id=purchased_order.business_id,
                        campaign_id="CMP-2026-000002",
                        credited_amount=None,
                        currency_code=purchased_order.currency_code,
                        created_at=EVALUATION_TIME,
                    )
                )
                session.flush()
        canonical = session.scalar(
            select(Attribution).where(Attribution.order_id == purchased_order.business_id)
        )
        assert canonical is not None
        assert evaluate_order_attribution(
            session,
            purchased_order,
            policy_version="click-last-touch-7d-v1",
        ) is canonical

        labels = [
            GroundTruthLabel(
                business_id=f"GT-ANOMALY-{index:02d}",
                evaluation_run_id=evaluation_run.business_id,
                label_code=label_code,
                entity_type=entity_type,
                entity_business_id=entity_id,
                expected=expected,
                label_payload={"fixture": "required-anomaly-scenarios"},
                recorded_at=EVALUATION_TIME,
            )
            for index, (label_code, entity_type, entity_id, expected) in enumerate(
                (
                    ("message_sent_after_opt_out", "message_event", "ME-ANOMALY-OPT-OUT", True),
                    (
                        "cart_abandoned_after_purchase",
                        "cart",
                        abandoned_cart.business_id,
                        True,
                    ),
                    ("stale_cart_total_after_quantity_update", "cart", stale_cart_id, True),
                    ("attribution_double_counted", "order", purchased_order.business_id, True),
                ),
                start=1,
            )
        ]
        session.add_all(labels)
        session.flush()

        findings = detect_operational_anomalies(session)
        fixture_findings = detect_attribution_fixture_anomalies(evaluation_run.results)
        detected = {finding.issue_type for finding in [*findings, *fixture_findings]}
        expected_positive = {
            label.label_code
            for label in session.scalars(
                select(GroundTruthLabel).where(
                    GroundTruthLabel.evaluation_run_id == evaluation_run.business_id,
                    GroundTruthLabel.expected.is_(True),
                    GroundTruthLabel.business_id.like("GT-ANOMALY-%"),
                )
            )
        }
        assert expected_positive == {
            "message_sent_after_opt_out",
            "cart_abandoned_after_purchase",
            "stale_cart_total_after_quantity_update",
            "attribution_double_counted",
        }
        assert expected_positive <= detected
        assert any(
            finding.entity_business_id == purchased_order.business_id
            for finding in fixture_findings
        )
        assert all(finding.issue_type != "attribution_double_counted" for finding in findings)
        assert withdrawal.business_id
        assert purchased_order.business_id


def test_schedule_creation_is_idempotent_and_incompatible_reuse_conflicts(generated_small_db) -> None:
    with Session(generated_small_db) as session, session.begin():
        cart = select_eligible_email_cart(session)
        policy = RecoveryPolicy()
        schedule_count_before = session.scalar(select(func.count(SendSchedule.business_id)))
        first = create_logical_schedule(
            session,
            cart_id=cart.business_id,
            channel="email",
            evaluated_at=EVALUATION_TIME,
            policy=policy,
        )
        assert first.eligible and first.schedule is not None
        schedule_count_after_create = session.scalar(select(func.count(SendSchedule.business_id)))
        assert schedule_count_after_create == schedule_count_before + 1

        prior_decisions = session.scalar(select(func.count(RecoveryDecision.business_id)))
        replay = create_logical_schedule(
            session,
            cart_id=cart.business_id,
            channel="email",
            evaluated_at=EVALUATION_TIME,
            policy=policy,
        )
        current_decisions = session.scalar(select(func.count(RecoveryDecision.business_id)))
        assert replay.idempotent_replay is True
        assert replay.schedule is not None
        assert replay.schedule.business_id == first.schedule.business_id
        schedule_count_after_replay = session.scalar(select(func.count(SendSchedule.business_id)))
        assert schedule_count_after_replay == schedule_count_after_create
        assert current_decisions == prior_decisions

        equivalent_offset = EVALUATION_TIME.astimezone(timezone(timedelta(hours=5)))
        offset_replay = create_logical_schedule(
            session,
            cart_id=cart.business_id,
            channel="email",
            evaluated_at=equivalent_offset,
            policy=policy,
        )
        assert offset_replay.idempotent_replay is True
        assert offset_replay.schedule is not None
        assert offset_replay.schedule.business_id == first.schedule.business_id
        assert session.scalar(select(func.count(SendSchedule.business_id))) == schedule_count_after_create

        incompatible_policy = replace(policy, frequency_cap_24h=policy.frequency_cap_24h + 1)
        with pytest.raises(IdempotencyConflictError):
            create_logical_schedule(
                session,
                cart_id=cart.business_id,
                channel="email",
                evaluated_at=EVALUATION_TIME,
                policy=incompatible_policy,
            )

        assert schedule_idempotency_key(cart.business_id, "email", policy.version) == first.schedule.idempotency_key


def test_concurrent_equivalent_schedule_requests_create_one_schedule(generated_small_db) -> None:
    with Session(generated_small_db) as session:
        cart = select_eligible_email_cart(session)
        cart_id = cart.business_id
        customer_id = cart.customer_id
    policy = RecoveryPolicy()

    def create_in_own_transaction():
        with Session(generated_small_db) as session, session.begin():
            result = create_logical_schedule(
                session,
                cart_id=cart_id,
                channel="email",
                evaluated_at=EVALUATION_TIME,
                policy=policy,
            )
            assert result.schedule is not None
            return result.schedule.business_id

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: create_in_own_transaction(), range(2)))
    assert results[0] == results[1]

    with Session(generated_small_db) as session:
        count = session.scalar(
            select(func.count(SendSchedule.business_id)).where(
                SendSchedule.customer_id == customer_id,
                SendSchedule.cart_id == cart_id,
                SendSchedule.policy_version == policy.version,
            )
        )
    assert count == 1