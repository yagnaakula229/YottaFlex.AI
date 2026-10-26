from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import Consent, ConsentEvent
from app.services.recovery.errors import IdempotencyConflictError, InvalidDecisionInputError
from app.services.recovery.decisions import require_aware

VALID_CONSENT_STATES = {"unknown", "granted", "denied"}
WITHDRAWAL_EVENT_TYPES = {"consent_revoked", "opt_out", "withdrawn", "unsubscribe"}


@dataclass(frozen=True)
class ConsentResolution:
    state: str
    allowed: bool
    source: str
    event_id: str | None
    effective_at: datetime | None
    reason_code: str | None


def resolve_effective_consent(
    session: Session,
    *,
    customer_id: str,
    channel: str,
    at: datetime,
) -> ConsentResolution:
    require_aware(at, "consent evaluation time")
    if not channel.strip():
        raise InvalidDecisionInputError("channel cannot be empty")

    event = session.scalar(
        select(ConsentEvent)
        .where(
            ConsentEvent.customer_id == customer_id,
            ConsentEvent.channel == channel,
            ConsentEvent.occurred_at <= at,
        )
        .order_by(ConsentEvent.occurred_at.desc(), ConsentEvent.business_id.desc())
        .limit(1)
    )
    if event is not None:
        if event.event_type.lower() in WITHDRAWAL_EVENT_TYPES:
            return ConsentResolution("denied", False, "consent_event", event.business_id, event.occurred_at, "consent_withdrawn")
        if event.state not in VALID_CONSENT_STATES:
            return ConsentResolution("invalid", False, "consent_event", event.business_id, event.occurred_at, "invalid_consent_state")
        allowed = event.state == "granted"
        return ConsentResolution(
            event.state,
            allowed,
            "consent_event",
            event.business_id,
            event.occurred_at,
            None if allowed else "consent_not_granted",
        )

    projection = session.scalar(
        select(Consent).where(
            Consent.customer_id == customer_id,
            Consent.channel == channel,
            Consent.updated_at <= at,
        )
    )
    if projection is None:
        return ConsentResolution("missing", False, "none", None, None, "consent_missing")
    if projection.state not in VALID_CONSENT_STATES:
        return ConsentResolution(
            "invalid", False, "projection", None, projection.updated_at, "invalid_consent_state"
        )
    allowed = projection.state == "granted"
    return ConsentResolution(
        projection.state,
        allowed,
        "projection",
        None,
        projection.updated_at,
        None if allowed else "consent_not_granted",
    )


def _consent_event_id(source_system: str, source_event_key: str) -> str:
    digest = hashlib.sha256(f"{source_system}\0{source_event_key}".encode("utf-8")).hexdigest()
    return f"CSE-{digest[:32]}"


def record_consent_change(
    session: Session,
    *,
    customer_id: str,
    channel: str,
    state: str,
    event_type: str,
    source_system: str,
    source_event_key: str,
    occurred_at: datetime,
    recorded_at: datetime,
) -> ConsentEvent:
    require_aware(occurred_at, "occurred_at")
    require_aware(recorded_at, "recorded_at")
    if not channel.strip() or state not in VALID_CONSENT_STATES:
        raise InvalidDecisionInputError("Consent channel and state must be valid")
    if not source_system or not source_event_key:
        raise InvalidDecisionInputError("Consent event source and idempotency key are required")

    values = {
        "business_id": _consent_event_id(source_system, source_event_key),
        "customer_id": customer_id,
        "channel": channel,
        "event_type": event_type,
        "state": state,
        "source_system": source_system,
        "source_event_key": source_event_key,
        "occurred_at": occurred_at,
        "recorded_at": recorded_at,
    }
    inserted_id = session.execute(
        pg_insert(ConsentEvent)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["source_system", "source_event_key"])
        .returning(ConsentEvent.business_id)
    ).scalar_one_or_none()
    event = session.scalar(
        select(ConsentEvent).where(
            ConsentEvent.source_system == source_system,
            ConsentEvent.source_event_key == source_event_key,
        )
    )
    if event is None:
        raise RuntimeError("Consent event insert was not visible in the current transaction")
    if inserted_id is None:
        comparable = (
            event.customer_id,
            event.channel,
            event.state,
            event.event_type,
            event.occurred_at,
            event.recorded_at,
        )
        requested = (customer_id, channel, state, event_type, occurred_at, recorded_at)
        if comparable != requested:
            raise IdempotencyConflictError("Consent event key was reused with incompatible contents")

    latest_event = session.scalar(
        select(ConsentEvent)
        .where(ConsentEvent.customer_id == customer_id, ConsentEvent.channel == channel)
        .order_by(ConsentEvent.occurred_at.desc(), ConsentEvent.business_id.desc())
        .limit(1)
    )
    assert latest_event is not None
    projected_state = (
        "denied"
        if latest_event.event_type.lower() in WITHDRAWAL_EVENT_TYPES
        else latest_event.state
    )
    projection_id = f"CON-{hashlib.sha256(f'{customer_id}\0{channel}'.encode('utf-8')).hexdigest()[:32]}"
    projection_insert = pg_insert(Consent).values(
        business_id=projection_id,
        customer_id=customer_id,
        channel=channel,
        last_event_id=latest_event.business_id,
        state=projected_state,
        updated_at=latest_event.occurred_at,
    )
    excluded = projection_insert.excluded
    session.execute(
        projection_insert
        .on_conflict_do_update(
            index_elements=["customer_id", "channel"],
            set_={
                "last_event_id": excluded.last_event_id,
                "state": projected_state,
                "updated_at": latest_event.occurred_at,
            },
            where=or_(
                excluded.updated_at > Consent.updated_at,
                and_(
                    excluded.updated_at == Consent.updated_at,
                    or_(
                        Consent.last_event_id.is_(None),
                        excluded.last_event_id > Consent.last_event_id,
                    ),
                ),
            ),
        )
    )
    return event