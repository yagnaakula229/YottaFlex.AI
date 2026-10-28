from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.models import Attribution, AttributionCandidate, AttributionDecision, MessageEvent, Order, SendAttempt, SendSchedule
from app.services.attribution.service import evaluate_order_attribution
from app.services.recovery.errors import InvalidDecisionInputError


class _FakeScalarResult:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, *, events=None, existing_attribution=None, conflict_on_flush=False, recovered_attribution=None):
        self.events = list(events or [])
        self.existing_attribution = existing_attribution
        self.conflict_on_flush = conflict_on_flush
        self.recovered_attribution = recovered_attribution
        self.rolled_back = False
        self.added = []

    def scalars(self, query):
        return _FakeScalarResult(self.events)

    def scalar(self, query):
        return self.existing_attribution

    def add(self, obj):
        self.added.append(obj)

    def flush(self, *args, **kwargs):
        if self.conflict_on_flush:
            pending = list(args[0]) if args and args[0] is not None else []
            if any(isinstance(obj, Attribution) for obj in pending):
                if self.recovered_attribution is not None:
                    self.existing_attribution = self.recovered_attribution
                self.conflict_on_flush = False
                raise IntegrityError("INSERT", {}, None)

    def rollback(self):
        self.rolled_back = True


def _make_order(*, business_id="ORD-1", customer_id="CUS-1", cart_id="CART-1", placed_at=None):
    return Order(
        business_id=business_id,
        customer_id=customer_id,
        cart_id=cart_id,
        status="paid",
        total_amount="99.99",
        currency_code="USD",
        placed_at=placed_at or datetime(2026, 10, 22, 12, 0, tzinfo=UTC),
    )


def _make_schedule(*, business_id="SCHED-1", customer_id="CUS-1", cart_id="CART-1", campaign_id="CMP-1"):
    return SendSchedule(
        business_id=business_id,
        idempotency_key=f"{business_id}-key",
        request_fingerprint="A" * 64,
        customer_id=customer_id,
        cart_id=cart_id,
        campaign_id=campaign_id,
        channel="email",
        policy_version="v1",
        policy_configuration_hash="B" * 64,
        status="sent",
        scheduled_for=datetime(2026, 10, 20, 8, 0, tzinfo=UTC),
        created_at=datetime(2026, 10, 20, 7, 0, tzinfo=UTC),
    )


def _make_attempt(*, business_id="SATT-1", schedule=None):
    attempt = SendAttempt(
        business_id=business_id,
        schedule_id=schedule.business_id,
        attempt_number=1,
        status="accepted",
        attempted_at=datetime(2026, 10, 22, 9, 0, tzinfo=UTC),
        provider_reference="SIM-123",
        error_detail=None,
    )
    attempt.schedule = schedule
    return attempt


def _make_click_event(*, business_id, occurred_at, schedule, send_attempt=None):
    effective_attempt = send_attempt or _make_attempt(business_id=f"{business_id}-attempt", schedule=schedule)
    event = MessageEvent(
        business_id=business_id,
        send_attempt_id=effective_attempt.business_id,
        event_type="clicked",
        source_system="provider-a",
        source_event_key=business_id,
        occurred_at=occurred_at,
        recorded_at=occurred_at,
        payload={"click_id": business_id},
    )
    event.send_attempt = effective_attempt
    effective_attempt.schedule = schedule
    return event


@pytest.mark.unit
def test_stage5_window_boundaries_are_inclusive_lower_and_exclusive_upper() -> None:
    order = _make_order(placed_at=datetime(2026, 10, 22, 12, 0, tzinfo=UTC))
    schedule = _make_schedule(campaign_id="CMP-LOWER")
    attempt = _make_attempt(schedule=schedule)
    included = _make_click_event(
        business_id="EVT-LOWER",
        occurred_at=datetime(2026, 10, 15, 12, 0, tzinfo=UTC),
        schedule=schedule,
        send_attempt=attempt,
    )
    excluded_upper = _make_click_event(
        business_id="EVT-UPPER",
        occurred_at=datetime(2026, 10, 22, 12, 0, tzinfo=UTC),
        schedule=schedule,
        send_attempt=attempt,
    )
    excluded_early = _make_click_event(
        business_id="EVT-EARLY",
        occurred_at=datetime(2026, 10, 15, 11, 59, 59, tzinfo=UTC),
        schedule=schedule,
        send_attempt=attempt,
    )

    session = _FakeSession(events=[included, excluded_upper, excluded_early])
    attribution = evaluate_order_attribution(session, order, policy_version="click-last-touch-v1")

    assert attribution is not None
    assert attribution.message_event_id == "EVT-LOWER"
    assert attribution.campaign_id == "CMP-LOWER"


@pytest.mark.unit
def test_stage5_latest_click_is_selected_and_ties_break_by_event_id() -> None:
    order = _make_order(placed_at=datetime(2026, 10, 22, 12, 0, tzinfo=UTC))
    schedule = _make_schedule(campaign_id="CMP-TIE")
    attempt = _make_attempt(schedule=schedule)
    older = _make_click_event(
        business_id="EVT-OLD",
        occurred_at=datetime(2026, 10, 20, 11, 0, tzinfo=UTC),
        schedule=schedule,
        send_attempt=attempt,
    )
    tied_a = _make_click_event(
        business_id="EVT-TIE-A",
        occurred_at=datetime(2026, 10, 21, 18, 0, tzinfo=UTC),
        schedule=schedule,
        send_attempt=attempt,
    )
    tied_b = _make_click_event(
        business_id="EVT-TIE-B",
        occurred_at=datetime(2026, 10, 21, 18, 0, tzinfo=UTC),
        schedule=schedule,
        send_attempt=attempt,
    )

    session = _FakeSession(events=[older, tied_a, tied_b])
    attribution = evaluate_order_attribution(session, order, policy_version="click-last-touch-v1")

    assert attribution is not None
    assert attribution.message_event_id == "EVT-TIE-B"


@pytest.mark.unit
def test_stage5_no_credit_creates_decision_but_no_canonical_attribution() -> None:
    order = _make_order(placed_at=datetime(2026, 10, 22, 12, 0, tzinfo=UTC))
    schedule = _make_schedule(campaign_id="CMP-NO-CREDIT")
    attempt = _make_attempt(schedule=schedule)
    out_of_window = _make_click_event(
        business_id="EVT-OUT",
        occurred_at=datetime(2026, 10, 14, 18, 0, tzinfo=UTC),
        schedule=schedule,
        send_attempt=attempt,
    )

    session = _FakeSession(events=[out_of_window])
    attribution = evaluate_order_attribution(session, order, policy_version="click-last-touch-v1")

    assert attribution is None
    decision = next(obj for obj in session.added if isinstance(obj, AttributionDecision))
    assert decision.outcome == "no_credit"
    assert decision.details["reason_code"] == "no_eligible_click"
    assert not any(isinstance(obj, Attribution) for obj in session.added)


@pytest.mark.unit
def test_stage5_repeated_evaluation_reuses_existing_canonical_row() -> None:
    order = _make_order()
    existing = Attribution(
        business_id="ATTR-EXISTING",
        order_id=order.business_id,
        decision_id="DEC-EXISTING",
        campaign_id="CMP-1",
        message_event_id="EVT-EXISTING",
        credited_amount=None,
        currency_code="USD",
        created_at=datetime(2026, 10, 22, 12, 5, tzinfo=UTC),
    )

    session = _FakeSession(existing_attribution=existing)
    attribution = evaluate_order_attribution(session, order, policy_version="click-last-touch-v1")

    assert attribution is existing
    assert session.added == []


@pytest.mark.unit
def test_stage5_conflict_on_canonical_insert_rolls_back_and_reuses_existing_row() -> None:
    order = _make_order(placed_at=datetime(2026, 10, 22, 12, 0, tzinfo=UTC))
    schedule = _make_schedule(campaign_id="CMP-RECOVER")
    attempt = _make_attempt(schedule=schedule)
    click = _make_click_event(
        business_id="EVT-RECOVER",
        occurred_at=datetime(2026, 10, 21, 12, 0, tzinfo=UTC),
        schedule=schedule,
        send_attempt=attempt,
    )
    existing = Attribution(
        business_id="ATTR-RECOVER",
        order_id=order.business_id,
        decision_id="DEC-RECOVER",
        campaign_id="CMP-RECOVER",
        message_event_id="EVT-RECOVER",
        credited_amount=None,
        currency_code="USD",
        created_at=datetime(2026, 10, 22, 12, 2, tzinfo=UTC),
    )

    session = _FakeSession(
        events=[click],
        conflict_on_flush=True,
        recovered_attribution=existing,
    )
    attribution = evaluate_order_attribution(session, order, policy_version="click-last-touch-v1")

    assert attribution is existing
    assert session.rolled_back is True


@pytest.mark.unit
def test_stage5_requires_timezone_aware_order_timestamp() -> None:
    order = _make_order(placed_at=datetime(2026, 10, 22, 12, 0))

    with pytest.raises(InvalidDecisionInputError):
        evaluate_order_attribution(_FakeSession(), order, policy_version="click-last-touch-v1")


@pytest.mark.unit
def test_stage5_keeps_decision_candidate_and_canonical_objects_separate() -> None:
    order = _make_order(placed_at=datetime(2026, 10, 22, 12, 0, tzinfo=UTC))
    schedule = _make_schedule(campaign_id="CMP-SEPARATE")
    attempt = _make_attempt(schedule=schedule)
    first = _make_click_event(
        business_id="EVT-FIRST",
        occurred_at=datetime(2026, 10, 20, 10, 0, tzinfo=UTC),
        schedule=schedule,
        send_attempt=attempt,
    )
    second = _make_click_event(
        business_id="EVT-SECOND",
        occurred_at=datetime(2026, 10, 21, 10, 0, tzinfo=UTC),
        schedule=schedule,
        send_attempt=attempt,
    )

    session = _FakeSession(events=[first, second])
    attribution = evaluate_order_attribution(session, order, policy_version="click-last-touch-v1")

    assert attribution is not None
    decision = next(obj for obj in session.added if isinstance(obj, AttributionDecision))
    candidates = [obj for obj in session.added if isinstance(obj, AttributionCandidate)]
    assert decision.outcome == "credited"
    assert decision.business_id == attribution.decision_id
    assert len(candidates) == 2
    assert {candidate.message_event_id for candidate in candidates} == {"EVT-FIRST", "EVT-SECOND"}
