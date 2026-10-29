from datetime import UTC, datetime

import pytest
from sqlalchemy.exc import IntegrityError

from app.services.message_events.service import (
    VALID_MESSAGE_EVENT_TYPES,
    canonicalize_message_event_payload,
    ingest_message_event,
)
from app.services.recovery.errors import IdempotencyConflictError, InvalidDecisionInputError


@pytest.mark.unit
def test_stage3_message_event_types_match_repo_contract() -> None:
    assert VALID_MESSAGE_EVENT_TYPES == {"sent", "delivered", "opened", "clicked"}


@pytest.mark.unit
def test_canonicalize_message_event_payload_normalizes_timestamps() -> None:
    payload = {
        "campaign_id": "CMP-2026-000001",
        "ts": "2026-10-22T12:00:00-04:00",
        "nested": {"at": datetime(2026, 10, 22, 12, 30, tzinfo=UTC)},
    }

    canonical = canonicalize_message_event_payload(payload)

    assert canonical["campaign_id"] == "CMP-2026-000001"
    assert canonical["ts"] == "2026-10-22T16:00:00Z"
    assert canonical["nested"]["at"] == "2026-10-22T12:30:00Z"


@pytest.mark.unit
def test_ingest_message_event_accepts_valid_payload() -> None:
    session = _FakeSession()

    event = ingest_message_event(
        session,
        send_attempt_id="SATT-123",
        event_type="sent",
        source_system="provider-a",
        source_event_key="evt-001",
        occurred_at=datetime(2026, 10, 22, 11, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 10, 22, 11, 0, 10, tzinfo=UTC),
        payload={"message_id": "MSG-1", "status": "queued"},
    )

    assert event.event_type == "sent"
    assert event.source_system == "provider-a"
    assert event.source_event_key == "evt-001"
    assert event.occurred_at == datetime(2026, 10, 22, 11, 0, tzinfo=UTC)
    assert event.payload == {"message_id": "MSG-1", "status": "queued"}


@pytest.mark.unit
def test_equivalent_duplicate_payload_is_idempotent() -> None:
    session = _FakeSession(
        existing_event=_ExistingEvent(
            payload={"message_id": "MSG-2", "when": "2026-10-22T11:00:00Z"},
        )
    )

    event = ingest_message_event(
        session,
        send_attempt_id="SATT-456",
        event_type="clicked",
        source_system="provider-a",
        source_event_key="evt-duplicate",
        occurred_at=datetime(2026, 10, 22, 11, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 10, 22, 11, 0, 1, tzinfo=UTC),
        payload={"message_id": "MSG-2", "when": "2026-10-22T11:00:00Z"},
    )

    assert event is session.existing_event


@pytest.mark.unit
def test_late_arriving_valid_event_is_accepted_and_preserved() -> None:
    session = _FakeSession()
    earlier = datetime(2026, 10, 21, 11, 0, tzinfo=UTC)

    event = ingest_message_event(
        session,
        send_attempt_id="SATT-LATE",
        event_type="opened",
        source_system="provider-a",
        source_event_key="evt-late-arrival",
        occurred_at=earlier,
        recorded_at=datetime(2026, 10, 22, 11, 0, tzinfo=UTC),
        payload={"message_id": "MSG-LATE", "when": "2026-10-21T11:00:00Z"},
    )

    assert event.occurred_at == earlier
    assert event.recorded_at == datetime(2026, 10, 22, 11, 0, tzinfo=UTC)
    assert event.payload == {"message_id": "MSG-LATE", "when": "2026-10-21T11:00:00Z"}


@pytest.mark.unit
def test_conflicting_duplicate_payload_raises_and_preserves_original() -> None:
    session = _FakeSession(
        existing_event=_ExistingEvent(payload={"message_id": "MSG-3", "when": "2026-10-22T11:00:00Z"})
    )

    with pytest.raises(IdempotencyConflictError):
        ingest_message_event(
            session,
            send_attempt_id="SATT-789",
            event_type="opened",
            source_system="provider-a",
            source_event_key="evt-conflict",
            occurred_at=datetime(2026, 10, 22, 11, 0, tzinfo=UTC),
            recorded_at=datetime(2026, 10, 22, 11, 0, 5, tzinfo=UTC),
            payload={"message_id": "MSG-3", "when": "2026-10-22T11:30:00Z"},
        )


@pytest.mark.unit
def test_invalid_event_type_or_timezone_is_rejected() -> None:
    with pytest.raises(InvalidDecisionInputError):
        ingest_message_event(
            _FakeSession(),
            send_attempt_id="SATT-000",
            event_type="bounced",
            source_system="provider-a",
            source_event_key="evt-bad",
            occurred_at=datetime(2026, 10, 22, 11, 0, tzinfo=UTC),
            recorded_at=datetime(2026, 10, 22, 11, 0, 1, tzinfo=UTC),
            payload={"message_id": "MSG-X"},
        )

    with pytest.raises(InvalidDecisionInputError):
        ingest_message_event(
            _FakeSession(),
            send_attempt_id="SATT-000",
            event_type="sent",
            source_system="provider-a",
            source_event_key="evt-naive",
            occurred_at=datetime(2026, 10, 22, 11, 0),
            recorded_at=datetime(2026, 10, 22, 11, 0, 1),
            payload={"message_id": "MSG-Y"},
        )


@pytest.mark.unit
def test_insert_race_rolls_back_and_rechecks_existing_row() -> None:
    existing_event = _ExistingEvent(payload={"message_id": "MSG-4", "when": "2026-10-22T11:00:00Z"})
    session = _FakeSession(existing_event=existing_event, conflict_on_flush=True)

    event = ingest_message_event(
        session,
        send_attempt_id="SATT-999",
        event_type="delivered",
        source_system="provider-a",
        source_event_key="evt-race",
        occurred_at=datetime(2026, 10, 22, 11, 0, tzinfo=UTC),
        recorded_at=datetime(2026, 10, 22, 11, 0, 2, tzinfo=UTC),
        payload={"message_id": "MSG-4", "when": "2026-10-22T11:00:00Z"},
    )

    assert event is existing_event
    assert session.rolled_back is True


class _ExistingEvent:
    def __init__(self, payload):
        self.payload = payload


class _FakeSession:
    def __init__(self, *, existing_event=None, conflict_on_flush=False):
        self._initial_existing_event = existing_event
        self.conflict_on_flush = conflict_on_flush
        self.rolled_back = False
        self.added = []
        self._scalar_calls = 0
        self.existing_event = existing_event if not conflict_on_flush else None

    def scalar(self, query):
        self._scalar_calls += 1
        if self.rolled_back:
            self.existing_event = self._initial_existing_event
            return self.existing_event
        if self.conflict_on_flush:
            if self._scalar_calls == 1:
                return None
            self.existing_event = self._initial_existing_event
            return self.existing_event
        return self.existing_event

    def add(self, obj):
        self.added.append(obj)

    def flush(self, *args, **kwargs):
        if self.conflict_on_flush:
            self.conflict_on_flush = False
            raise IntegrityError("INSERT", {}, None)

    def rollback(self):
        self.rolled_back = True
