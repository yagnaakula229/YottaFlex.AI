from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.services.execution.dispatch import (
    ProviderOutcome,
    determine_provider_outcome,
    dispatch_schedule_attempt,
)
from app.services.execution.due_schedule import ScheduleExecutionResult, prepare_send_attempt
from app.services.recovery.policy import RecoveryPolicy


class _FakeSession:
    def __init__(self):
        self.attempts = []

    def add(self, obj):
        self.attempts.append(obj)

    def flush(self, *args, **kwargs):
        return None

    def scalar(self, query):
        rendered = str(query).lower()
        if "max" in rendered:
            if not self.attempts:
                return 0
            return max(item.attempt_number for item in self.attempts)
        return None


class _ScheduleStub:
    def __init__(self, *, business_id="SCHED-1", customer_id="CUS-1", cart_id="CART-1", channel="email", status="scheduled"):
        self.business_id = business_id
        self.customer_id = customer_id
        self.cart_id = cart_id
        self.channel = channel
        self.status = status
        self.recovery_decision_id = None


@pytest.mark.unit
def test_provider_outcome_is_deterministic_for_accepted_case() -> None:
    outcome = determine_provider_outcome("SCHED-1", 1, forced_outcome="accepted")

    assert isinstance(outcome, ProviderOutcome)
    assert outcome.status == "accepted"
    assert outcome.retryable is False
    assert outcome.provider_reference.startswith("SIM-")
    assert outcome.error_detail is None


@pytest.mark.unit
def test_provider_outcome_is_deterministic_for_retryable_failure() -> None:
    outcome = determine_provider_outcome("SCHED-1", 1, forced_outcome="retryable_failure")

    assert outcome.status == "failed"
    assert outcome.retryable is True
    assert outcome.error_detail == "retryable_provider_failure"


@pytest.mark.unit
def test_provider_outcome_is_deterministic_for_permanent_failure() -> None:
    outcome = determine_provider_outcome("SCHED-1", 1, forced_outcome="permanent_failure")

    assert outcome.status == "failed"
    assert outcome.retryable is False
    assert outcome.error_detail == "permanent_provider_failure"


@pytest.mark.unit
def test_dispatch_attempt_uses_next_attempt_number_and_marks_schedule_sent(monkeypatch) -> None:
    session = _FakeSession()
    schedule = _ScheduleStub()

    monkeypatch.setattr(
        "app.services.execution.dispatch.recheck_schedule_eligibility",
        lambda *args, **kwargs: ScheduleExecutionResult(
            schedule=schedule,
            eligible=True,
            reason_code=None,
            decision=None,
            attempt=None,
        ),
    )

    result = dispatch_schedule_attempt(
        session,
        schedule,
        attempted_at=datetime(2026, 10, 22, 12, 2, tzinfo=UTC),
        force_outcome="accepted",
    )

    assert result.attempt is not None
    assert result.attempt.attempt_number == 1
    assert result.attempt.status == "accepted"
    assert result.schedule.status == "sent"
    assert result.provider_result.status == "accepted"


@pytest.mark.unit
def test_dispatch_attempt_marks_schedule_retryable_then_failed(monkeypatch) -> None:
    session = _FakeSession()
    schedule = _ScheduleStub()

    monkeypatch.setattr(
        "app.services.execution.dispatch.recheck_schedule_eligibility",
        lambda *args, **kwargs: ScheduleExecutionResult(
            schedule=schedule,
            eligible=True,
            reason_code=None,
            decision=None,
            attempt=None,
        ),
    )

    result = dispatch_schedule_attempt(
        session,
        schedule,
        attempted_at=datetime(2026, 10, 22, 12, 2, tzinfo=UTC),
        force_outcome="retryable_failure",
    )

    assert result.provider_result.retryable is True
    assert result.attempt.status == "failed"
    assert result.schedule.status == "scheduled"


@pytest.mark.unit
def test_dispatch_attempt_suppresses_when_execution_recheck_fails(monkeypatch) -> None:
    session = _FakeSession()
    schedule = _ScheduleStub()

    schedule.status = "scheduled"

    def fake_recheck(*args, **kwargs):
        return ScheduleExecutionResult(
            schedule=schedule,
            eligible=False,
            reason_code="consent_withdrawn",
            decision=None,
            attempt=None,
        )

    monkeypatch.setattr(
        "app.services.execution.dispatch.recheck_schedule_eligibility",
        fake_recheck,
    )

    result = dispatch_schedule_attempt(
        session,
        schedule,
        attempted_at=datetime(2026, 10, 22, 12, 2, tzinfo=UTC),
    )

    assert result.eligible is False
    assert result.reason_code == "consent_withdrawn"
    assert result.attempt is None
    assert result.schedule.status == "suppressed"


@pytest.mark.unit
def test_prepare_send_attempt_raises_explicit_conflict_on_duplicate_allocation(monkeypatch) -> None:
    schedule = _ScheduleStub()

    class _ConflictSession(_FakeSession):
        def scalar(self, query):
            rendered = str(query).lower()
            if "max" in rendered:
                return 1
            return "SATT-DUPLICATE"

        def flush(self, *args, **kwargs):
            raise IntegrityError("INSERT", {}, None)

    session = _ConflictSession()
    monkeypatch.setattr("app.services.execution.due_schedule._lock_schedule_for_attempt", lambda *args, **kwargs: None)

    with pytest.raises(RuntimeError, match="logical attempt allocation conflict"):
        prepare_send_attempt(
            session,
            schedule,
            attempted_at=datetime(2026, 10, 22, 12, 2, tzinfo=UTC),
        )


@pytest.mark.unit
def test_recovery_policy_counts_only_accepted_attempts() -> None:
    policy = RecoveryPolicy()

    assert policy.qualifying_attempt_states == ("accepted",)
    assert "failed" not in policy.qualifying_attempt_states
