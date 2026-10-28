from datetime import UTC, datetime, timedelta

import pytest

from app.services.execution.due_schedule import (
    prepare_send_attempt,
    select_due_schedules,
)


@pytest.mark.unit
class _ScheduleRow:
    def __init__(self, business_id, status, scheduled_for, channel="email"):
        self.business_id = business_id
        self.status = status
        self.scheduled_for = scheduled_for
        self.channel = channel
        self.customer_id = "CUS-UNIT-1"
        self.cart_id = "CART-UNIT-1"
        self.campaign_id = "CMP-UNIT-1"
        self.recovery_decision_id = None

class _FakeScalarResult:
    def __init__(self, value):
        self._value = value

    def all(self):
        return self._value


class _FakeExecuteResult:
    def __init__(self, rows):
        self._rows = rows

    def scalars(self):
        return _FakeScalarResult(self._rows)


class _FakeSession:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.attempts = []

    def execute(self, query):
        return _FakeExecuteResult(self.rows)

    def scalar(self, query):
        rendered = str(query).lower()
        if "max" in rendered:
            if not self.attempts:
                return 0
            return max(item["attempt_number"] for item in self.attempts)
        return None

    def add(self, obj):
        self.attempts.append({"attempt_number": obj.attempt_number, "schedule_id": obj.schedule_id})

    def flush(self, *args, **kwargs):
        return None


@pytest.mark.unit
def test_select_due_schedules_filters_only_due_scheduled_rows() -> None:
    now = datetime(2026, 10, 22, 12, 0, tzinfo=UTC)
    due = _ScheduleRow("SCHED-1", "scheduled", now - timedelta(minutes=5))
    not_due = _ScheduleRow("SCHED-2", "scheduled", now + timedelta(minutes=5))
    suppressed = _ScheduleRow("SCHED-3", "suppressed", now - timedelta(minutes=5))
    rows = [due, not_due, suppressed]

    selected = select_due_schedules(_FakeSession(rows), evaluated_at=now)

    assert [row.business_id for row in selected] == ["SCHED-1"]


@pytest.mark.unit
def test_prepare_send_attempt_uses_next_attempt_number() -> None:
    session = _FakeSession()
    schedule = _ScheduleRow("SCHED-9", "scheduled", datetime(2026, 10, 22, 12, 0, tzinfo=UTC))

    attempt = prepare_send_attempt(session, schedule, attempted_at=datetime(2026, 10, 22, 12, 2, tzinfo=UTC))

    assert attempt.schedule_id == "SCHED-9"
    assert attempt.attempt_number == 1
    assert session.attempts[0]["attempt_number"] == 1
