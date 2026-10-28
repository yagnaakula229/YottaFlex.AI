from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import MessageEvent
from app.services.recovery.decisions import require_aware
from app.services.recovery.errors import IdempotencyConflictError, InvalidDecisionInputError

VALID_MESSAGE_EVENT_TYPES = {"sent", "delivered", "opened", "clicked"}


def canonicalize_message_event_payload(payload: Any) -> dict[str, Any]:
    if payload is None or not isinstance(payload, Mapping):
        raise InvalidDecisionInputError("message event payload must be a JSON object")
    canonical = _canonicalize_value(payload)
    if not isinstance(canonical, dict):
        raise InvalidDecisionInputError("message event payload must be a JSON object")
    return canonical


def _canonicalize_value(value: Any) -> Any:
    if isinstance(value, datetime):
        aware = value if value.tzinfo is not None and value.utcoffset() is not None else value.replace(tzinfo=UTC)
        return aware.astimezone(UTC).isoformat().replace("+00:00", "Z")

    if isinstance(value, str):
        text = value.strip()
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return value
        if parsed.tzinfo is not None and parsed.utcoffset() is not None:
            return parsed.astimezone(UTC).isoformat().replace("+00:00", "Z")
        return value

    if isinstance(value, list):
        return [_canonicalize_value(item) for item in value]

    if isinstance(value, tuple):
        return [_canonicalize_value(item) for item in value]

    if isinstance(value, set):
        return [_canonicalize_value(item) for item in sorted(value, key=lambda item: json.dumps(_canonicalize_value(item), sort_keys=True, separators=(",", ":")))]

    if isinstance(value, Mapping):
        return {
            str(key): _canonicalize_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }

    if value is None or isinstance(value, (bool, int, float)):
        return value

    return str(value)


def _existing_message_event(session: Session, *, source_system: str, source_event_key: str) -> MessageEvent | None:
    return session.scalar(
        select(MessageEvent).where(
            MessageEvent.source_system == source_system,
            MessageEvent.source_event_key == source_event_key,
        )
    )


def _message_event_business_id(source_system: str, source_event_key: str) -> str:
    digest = hashlib.sha256(f"{source_system}\0{source_event_key}".encode("utf-8")).hexdigest()
    return f"MSE-{digest[:32]}"


def ingest_message_event(
    session: Session,
    *,
    send_attempt_id: str,
    event_type: str,
    source_system: str,
    source_event_key: str,
    occurred_at: datetime,
    recorded_at: datetime,
    payload: Any,
) -> MessageEvent:
    require_aware(occurred_at, "occurred_at")
    require_aware(recorded_at, "recorded_at")

    if not send_attempt_id or not send_attempt_id.strip():
        raise InvalidDecisionInputError("send_attempt_id is required")
    if not source_system or not source_system.strip():
        raise InvalidDecisionInputError("source_system is required")
    if not source_event_key or not source_event_key.strip():
        raise InvalidDecisionInputError("source_event_key is required")
    normalized_event_type = event_type.strip().lower()
    if normalized_event_type not in VALID_MESSAGE_EVENT_TYPES:
        raise InvalidDecisionInputError(
            f"event_type '{event_type}' is not supported; allowed values are {sorted(VALID_MESSAGE_EVENT_TYPES)}"
        )

    canonical_payload = canonicalize_message_event_payload(payload)

    existing = _existing_message_event(
        session,
        source_system=source_system,
        source_event_key=source_event_key,
    )
    if existing is not None:
        if canonicalize_message_event_payload(existing.payload) == canonical_payload:
            return existing
        raise IdempotencyConflictError(
            "Message event source key was reused with incompatible contents; preserving the original record."
        )

    event = MessageEvent(
        business_id=_message_event_business_id(source_system, source_event_key),
        send_attempt_id=send_attempt_id,
        event_type=normalized_event_type,
        source_system=source_system,
        source_event_key=source_event_key,
        occurred_at=occurred_at.astimezone(UTC),
        recorded_at=recorded_at.astimezone(UTC),
        payload=canonical_payload,
    )
    session.add(event)
    try:
        session.flush([event])
    except IntegrityError as exc:
        session.rollback()
        recovered = _existing_message_event(
            session,
            source_system=source_system,
            source_event_key=source_event_key,
        )
        if recovered is not None:
            if canonicalize_message_event_payload(recovered.payload) == canonical_payload:
                return recovered
            raise IdempotencyConflictError(
                "Message event source key was reused with incompatible contents; preserving the original record."
            ) from exc
        raise
    return event
