from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.models import SendSchedule
from app.services.recovery.decisions import require_aware
from app.services.recovery.eligibility import EligibilityEvaluation, evaluate_customer_channel_eligibility
from app.services.recovery.errors import IdempotencyConflictError
from app.services.recovery.policy import RecoveryPolicy


@dataclass(frozen=True)
class ScheduleCreationResult:
    eligible: bool
    reason_code: str | None
    schedule: SendSchedule | None
    evaluation: EligibilityEvaluation | None
    idempotent_replay: bool


def schedule_idempotency_key(cart_id: str, channel: str, policy_version: str) -> str:
    material = f"recovery-schedule\0{cart_id}\0{channel}\0{policy_version}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _request_fingerprint(
    *,
    cart_id: str,
    channel: str,
    evaluated_at: datetime,
    scheduled_for: datetime,
    policy: RecoveryPolicy,
) -> str:
    payload = {
        "cart_id": cart_id,
        "channel": channel,
        "evaluated_at": evaluated_at.astimezone(UTC).isoformat(timespec="microseconds"),
        "scheduled_for": scheduled_for.astimezone(UTC).isoformat(timespec="microseconds"),
        "policy_version": policy.version,
        "configuration_hash": policy.configuration_hash,
    }
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _existing_schedule(
    session: Session,
    *,
    key: str,
    fingerprint: str,
) -> SendSchedule | None:
    existing = session.scalar(select(SendSchedule).where(SendSchedule.idempotency_key == key))
    if existing is None:
        return None
    if existing.request_fingerprint != fingerprint:
        raise IdempotencyConflictError("Schedule idempotency key was reused with incompatible inputs")
    return existing


def create_logical_schedule(
    session: Session,
    *,
    cart_id: str,
    channel: str,
    evaluated_at: datetime,
    scheduled_for: datetime | None = None,
    policy: RecoveryPolicy | None = None,
) -> ScheduleCreationResult:
    require_aware(evaluated_at, "evaluated_at")
    due_at = scheduled_for or evaluated_at
    require_aware(due_at, "scheduled_for")
    effective_policy = policy or RecoveryPolicy.from_settings()
    idempotency_key = schedule_idempotency_key(cart_id, channel, effective_policy.version)
    fingerprint = _request_fingerprint(
        cart_id=cart_id,
        channel=channel,
        evaluated_at=evaluated_at,
        scheduled_for=due_at,
        policy=effective_policy,
    )

    existing = _existing_schedule(session, key=idempotency_key, fingerprint=fingerprint)
    if existing is not None:
        return ScheduleCreationResult(True, None, existing, None, True)

    evaluation = evaluate_customer_channel_eligibility(
        session,
        cart_id=cart_id,
        channel=channel,
        evaluated_at=evaluated_at,
        policy=effective_policy,
    )
    if not evaluation.eligible:
        return ScheduleCreationResult(False, evaluation.reason_code, None, evaluation, False)

    assert evaluation.selection is not None
    schedule_business_id = f"SEND-{idempotency_key[:32]}"
    values = {
        "business_id": schedule_business_id,
        "idempotency_key": idempotency_key,
        "request_fingerprint": fingerprint,
        "customer_id": evaluation.decision.customer_id,
        "cart_id": cart_id,
        "campaign_id": evaluation.selection.campaign_id,
        "recovery_decision_id": evaluation.decision.business_id,
        "channel": channel,
        "policy_version": effective_policy.version,
        "policy_configuration_hash": effective_policy.configuration_hash,
        "status": "scheduled",
        "scheduled_for": due_at,
        "created_at": evaluated_at,
    }
    inserted_id = session.execute(
        pg_insert(SendSchedule)
        .values(**values)
        .on_conflict_do_nothing(index_elements=["idempotency_key"])
        .returning(SendSchedule.business_id)
    ).scalar_one_or_none()
    schedule = session.scalar(select(SendSchedule).where(SendSchedule.idempotency_key == idempotency_key))
    if schedule is None:
        raise RuntimeError("Schedule insert was not visible in the current transaction")
    if inserted_id is None and schedule.request_fingerprint != fingerprint:
        raise IdempotencyConflictError("Schedule idempotency key was concurrently reused with incompatible inputs")
    return ScheduleCreationResult(True, None, schedule, evaluation, inserted_id is None)