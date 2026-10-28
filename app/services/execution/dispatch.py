from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
from typing import Any

from sqlalchemy.orm import Session

from app.models import SendAttempt, SendSchedule
from app.services.execution.due_schedule import prepare_send_attempt, recheck_schedule_eligibility


@dataclass(frozen=True)
class ProviderOutcome:
    outcome: str
    status: str
    provider_reference: str
    retryable: bool
    error_detail: str | None


@dataclass(frozen=True)
class DispatchResult:
    schedule: SendSchedule
    eligible: bool
    reason_code: str | None
    decision: Any | None = None
    attempt: SendAttempt | None = None
    provider_result: ProviderOutcome | None = None


def _provider_reference(schedule_id: str, attempt_number: int, *, provider_name: str = "simulated-provider") -> str:
    digest = sha256(f"{provider_name}|{schedule_id}|{attempt_number}".encode("utf-8")).hexdigest()
    return f"SIM-{digest[:32]}"


def determine_provider_outcome(
    schedule_id: str,
    attempt_number: int,
    *,
    forced_outcome: str | None = None,
    provider_name: str = "simulated-provider",
) -> ProviderOutcome:
    outcome = (forced_outcome or "").strip().lower()
    if outcome and outcome not in {"accepted", "retryable_failure", "permanent_failure"}:
        raise ValueError(f"Unsupported simulated dispatch outcome: {forced_outcome!r}")

    if not outcome:
        digest = sha256(f"{provider_name}|{schedule_id}|{attempt_number}".encode("utf-8")).hexdigest()
        bucket = int(digest[:8], 16) % 100
        if bucket < 70:
            outcome = "accepted"
        elif bucket < 90:
            outcome = "permanent_failure"
        else:
            outcome = "retryable_failure"

    if outcome == "accepted":
        return ProviderOutcome(
            outcome=outcome,
            status="accepted",
            provider_reference=_provider_reference(schedule_id, attempt_number, provider_name=provider_name),
            retryable=False,
            error_detail=None,
        )
    if outcome == "retryable_failure":
        return ProviderOutcome(
            outcome=outcome,
            status="failed",
            provider_reference=_provider_reference(schedule_id, attempt_number, provider_name=provider_name),
            retryable=True,
            error_detail="retryable_provider_failure",
        )
    return ProviderOutcome(
        outcome=outcome,
        status="failed",
        provider_reference=_provider_reference(schedule_id, attempt_number, provider_name=provider_name),
        retryable=False,
        error_detail="permanent_provider_failure",
    )


def dispatch_schedule_attempt(
    session: Session,
    schedule: SendSchedule,
    *,
    attempted_at: datetime,
    policy: object | None = None,
    force_outcome: str | None = None,
    provider_name: str = "simulated-provider",
) -> DispatchResult:
    execution_result = recheck_schedule_eligibility(
        session,
        schedule=schedule,
        evaluated_at=attempted_at,
        policy=policy,
    )
    if not execution_result.eligible:
        schedule.status = "suppressed"
        if hasattr(session, "flush"):
            session.flush()
        return DispatchResult(
            schedule=schedule,
            eligible=False,
            reason_code=execution_result.reason_code,
            decision=execution_result.decision,
            attempt=None,
            provider_result=None,
        )

    attempt = prepare_send_attempt(session, schedule, attempted_at=attempted_at)
    provider_result = determine_provider_outcome(
        schedule.business_id,
        attempt.attempt_number,
        forced_outcome=force_outcome,
        provider_name=provider_name,
    )
    attempt.status = provider_result.status
    attempt.provider_reference = provider_result.provider_reference
    attempt.error_detail = provider_result.error_detail

    if provider_result.status == "accepted":
        schedule.status = "sent"
    elif provider_result.retryable:
        schedule.status = "scheduled"
    else:
        schedule.status = "failed"

    if hasattr(session, "flush"):
        session.flush()

    return DispatchResult(
        schedule=schedule,
        eligible=True,
        reason_code=None,
        decision=execution_result.decision,
        attempt=attempt,
        provider_result=provider_result,
    )
