from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from app.services.recovery.consent import resolve_effective_consent
from app.services.recovery.eligibility import select_campaign_template
from app.services.recovery.policy import RecoveryPolicy
from app.services.recovery.scheduling import schedule_idempotency_key

pytestmark = pytest.mark.unit


class _FakeQueryResult:
    def __init__(self, value):
        self._value = value

    def first(self):
        return self._value


class _FakeSession:
    def __init__(self, *, event=None, selection=None):
        self.event = event
        self.selection = selection

    def scalar(self, _query):
        return self.event

    def execute(self, _query):
        return _FakeQueryResult(self.selection)


def test_policy_configuration_is_versioned_and_hashes_all_decision_inputs() -> None:
    default_policy = RecoveryPolicy()
    changed_threshold = replace(
        default_policy,
        inactivity_threshold=timedelta(minutes=90),
    )

    assert default_policy.version == "recovery-v1-provisional"
    assert default_policy.as_dict()["rolling_window_boundary"] == "(lower, upper]"
    assert default_policy.configuration_hash != changed_threshold.configuration_hash


def test_policy_rejects_unsupported_or_invalid_values() -> None:
    with pytest.raises(ValueError, match="Frequency caps"):
        RecoveryPolicy(frequency_cap_24h=-1)

    with pytest.raises(ValueError, match="selection policy"):
        RecoveryPolicy(selection_policy="random")


def test_consent_resolution_prefers_latest_event_and_uses_withdrawal_code() -> None:
    newer_event = type(
        "ConsentEventStub",
        (),
        {
            "business_id": "CSE-300",
            "channel": "email",
            "customer_id": "CUS-UNIT-1",
            "event_type": "consent_revoked",
            "state": "granted",
            "occurred_at": datetime(2026, 10, 22, 11, 0, tzinfo=UTC),
        },
    )()
    session = _FakeSession(event=newer_event)

    resolution = resolve_effective_consent(
        session,
        customer_id="CUS-UNIT-1",
        channel="email",
        at=datetime(2026, 10, 22, 12, 0, tzinfo=UTC),
    )

    assert resolution.state == "denied"
    assert resolution.allowed is False
    assert resolution.reason_code == "consent_withdrawn"
    assert resolution.event_id == "CSE-300"


def test_campaign_selection_selects_highest_priority_active_template() -> None:
    session = _FakeSession(selection=("CMP-2026-000001", 0, "TPL-2026-000001"))

    selection = select_campaign_template(
        session,
        channel="email",
        evaluated_at=datetime(2026, 10, 22, 12, 0, tzinfo=UTC),
    )

    assert selection is not None
    assert selection.campaign_id == "CMP-2026-000001"
    assert selection.template_id == "TPL-2026-000001"
    assert selection.priority == 0


def test_schedule_idempotency_key_is_stable_for_equivalent_requests() -> None:
    key_a = schedule_idempotency_key("CART-123", "email", "recovery-v1-provisional")
    key_b = schedule_idempotency_key("CART-123", "email", "recovery-v1-provisional")
    assert key_a == key_b

    key_c = schedule_idempotency_key("CART-124", "email", "recovery-v1-provisional")
    key_d = schedule_idempotency_key("CART-123", "sms", "recovery-v1-provisional")
    key_e = schedule_idempotency_key("CART-123", "email", "recovery-v2")

    assert key_a != key_c
    assert key_a != key_d
    assert key_a != key_e

