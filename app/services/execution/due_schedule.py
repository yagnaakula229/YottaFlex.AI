from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import RecoveryDecision, SendAttempt, SendSchedule
from app.services.recovery.decisions import record_decision
from app.services.recovery.eligibility import evaluate_customer_channel_eligibility
from app.services.recovery.policy import RecoveryPolicy


@dataclass(frozen=True)
class ScheduleExecutionResult:
    schedule: SendSchedule
    eligible: bool
    reason_code: str | None
    decision: RecoveryDecision | None = None
    attempt: SendAttempt | None = None


def select_due_schedules(
    session: Session,
    *,
    evaluated_at: datetime,
    limit: int | None = None,
    include_statuses: tuple[str, ...] = ("scheduled",),
) -> list[SendSchedule]:
    query = (
        select(SendSchedule)
        .where(
            SendSchedule.status.in_(include_statuses),
            SendSchedule.scheduled_for <= evaluated_at,
        )
        .order_by(SendSchedule.scheduled_for.asc(), SendSchedule.business_id.asc())
    )
    if limit is not None:
        query = query.limit(limit)

    bind = getattr(session, "bind", None)
    if bind is not None and getattr(bind, "dialect", None) is not None and bind.dialect.name == "postgresql":
        query = query.with_for_update(skip_locked=True)

    rows = session.execute(query).scalars().all()
    return [
        row
        for row in rows
        if getattr(row, "status", None) in include_statuses
        and getattr(row, "scheduled_for", None) is not None
        and getattr(row, "scheduled_for") <= evaluated_at
    ]


def suppress_schedule(
    session: Session,
    *,
    schedule: SendSchedule,
    reason_code: str,
    evaluated_at: datetime,
    policy: RecoveryPolicy | None = None,
    evidence: dict[str, object] | None = None,
) -> RecoveryDecision:
    effective_policy = policy or RecoveryPolicy.from_settings()
    decision = record_decision(
        session,
        decision_type="eligibility",
        cart_id=schedule.cart_id,
        customer_id=schedule.customer_id,
        channel=schedule.channel,
        evaluated_at=evaluated_at,
        policy=effective_policy,
        outcome="suppressed",
        reason_code=reason_code,
        evidence=evidence or {"schedule_status": "suppressed", "reason_code": reason_code},
    )
    schedule.status = "suppressed"
    schedule.recovery_decision_id = decision.business_id
    if hasattr(session, "flush"):
        session.flush()
    return decision


def recheck_schedule_eligibility(
    session: Session,
    *,
    schedule: SendSchedule,
    evaluated_at: datetime,
    policy: RecoveryPolicy | None = None,
) -> ScheduleExecutionResult:
    if schedule.status != "scheduled":
        return ScheduleExecutionResult(
            schedule=schedule,
            eligible=False,
            reason_code="schedule_not_scheduled",
            decision=None,
            attempt=None,
        )

    evaluation = evaluate_customer_channel_eligibility(
        session,
        cart_id=schedule.cart_id,
        channel=schedule.channel,
        evaluated_at=evaluated_at,
        policy=policy,
    )
    schedule.recovery_decision_id = evaluation.decision.business_id
    schedule.status = "suppressed" if not evaluation.eligible else "processing"
    if hasattr(session, "flush"):
        session.flush()
    return ScheduleExecutionResult(
        schedule=schedule,
        eligible=evaluation.eligible,
        reason_code=evaluation.reason_code,
        decision=evaluation.decision,
        attempt=None,
    )


def _lock_schedule_for_attempt(session: Session, *, schedule: SendSchedule) -> None:
    bind = getattr(session, "bind", None)
    if bind is None or getattr(bind, "dialect", None) is None or bind.dialect.name != "postgresql":
        return

    row = session.execute(
        select(SendSchedule)
        .where(SendSchedule.business_id == schedule.business_id)
        .with_for_update()
    ).scalar_one_or_none()
    if row is None:
        raise RuntimeError(f"Schedule row not found while allocating send attempt for {schedule.business_id}")


def prepare_send_attempt(
    session: Session,
    schedule: SendSchedule,
    *,
    attempted_at: datetime,
    provider_reference: str | None = None,
    status: str = "started",
    error_detail: str | None = None,
) -> SendAttempt:
    _lock_schedule_for_attempt(session, schedule=schedule)

    next_number = int(
        session.scalar(
            select(func.coalesce(func.max(SendAttempt.attempt_number), 0))
            .where(SendAttempt.schedule_id == schedule.business_id)
        )
        + 1
    )

    existing = session.scalar(
        select(SendAttempt.business_id)
        .where(
            SendAttempt.schedule_id == schedule.business_id,
            SendAttempt.attempt_number == next_number,
        )
        .limit(1)
    )
    if existing is not None:
        raise RuntimeError(
            f"Attempt number {next_number} already exists for schedule {schedule.business_id}; "
            "logical attempt allocation conflict detected."
        )

    attempt = SendAttempt(
        business_id=f"SATT-{uuid4().hex}",
        schedule_id=schedule.business_id,
        attempt_number=next_number,
        status=status,
        attempted_at=attempted_at,
        provider_reference=provider_reference,
        error_detail=error_detail,
    )
    session.add(attempt)
    try:
        if hasattr(session, "flush"):
            session.flush([attempt])
    except IntegrityError as exc:
        conflicting = session.scalar(
            select(SendAttempt.business_id)
            .where(
                SendAttempt.schedule_id == schedule.business_id,
                SendAttempt.attempt_number == next_number,
            )
            .limit(1)
        )
        if conflicting is not None:
            raise RuntimeError(
                f"Attempt number {next_number} already exists for schedule {schedule.business_id}; "
                "logical attempt allocation conflict detected."
            ) from exc
        raise
    return attempt


def execute_due_schedules(
    session: Session,
    *,
    evaluated_at: datetime,
    limit: int | None = None,
    policy: RecoveryPolicy | None = None,
) -> list[ScheduleExecutionResult]:
    due_schedules = select_due_schedules(session, evaluated_at=evaluated_at, limit=limit)
    return [
        recheck_schedule_eligibility(
            session,
            schedule=schedule,
            evaluated_at=evaluated_at,
            policy=policy,
        )
        for schedule in due_schedules
    ]
