from __future__ import annotations

from datetime import UTC, datetime, timedelta
from hashlib import sha256
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import (
    Attribution,
    AttributionCandidate,
    AttributionDecision,
    MessageEvent,
    Order,
    SendAttempt,
    SendSchedule,
)
from app.services.recovery.decisions import require_aware
from app.services.recovery.errors import InvalidDecisionInputError


def _stable_business_id(prefix: str, *parts: str) -> str:
    encoded = "\0".join(parts).encode("utf-8")
    digest = sha256(encoded).hexdigest()
    return f"{prefix}-{digest[:32]}"


def _existing_canonical_attribution(session: Session, order_id: str) -> Attribution | None:
    return session.scalar(select(Attribution).where(Attribution.order_id == order_id))


def _resolve_event_schedule(event: MessageEvent) -> SendSchedule | None:
    send_attempt = getattr(event, "send_attempt", None)
    if send_attempt is None:
        return None
    return getattr(send_attempt, "schedule", None)


def _eligible_clicks_for_order(session: Session, order: Order) -> list[MessageEvent]:
    if order.cart_id is None:
        return []

    window_start = order.placed_at - timedelta(days=7)
    query = (
        select(MessageEvent)
        .join(SendAttempt, SendAttempt.business_id == MessageEvent.send_attempt_id)
        .join(SendSchedule, SendSchedule.business_id == SendAttempt.schedule_id)
        .where(
            MessageEvent.event_type == "clicked",
            MessageEvent.occurred_at >= window_start,
            MessageEvent.occurred_at < order.placed_at,
            SendSchedule.customer_id == order.customer_id,
            SendSchedule.cart_id == order.cart_id,
        )
        .order_by(MessageEvent.occurred_at.desc(), MessageEvent.business_id.desc())
    )

    events = session.scalars(query).all()
    selected: list[MessageEvent] = []
    for event in events:
        if event.event_type != "clicked":
            continue
        if not (window_start <= event.occurred_at < order.placed_at):
            continue
        schedule = _resolve_event_schedule(event)
        if schedule is None:
            continue
        if schedule.customer_id != order.customer_id or schedule.cart_id != order.cart_id:
            continue
        selected.append(event)
    return sorted(
        selected,
        key=lambda event: (event.occurred_at, event.business_id),
        reverse=True,
    )


def _write_no_credit_decision(
    session: Session,
    *,
    order: Order,
    policy_version: str,
    decided_at: datetime,
    reason_code: str,
    window_start: datetime,
) -> None:
    decision = AttributionDecision(
        business_id=_stable_business_id("ATTRD", order.business_id, policy_version, reason_code),
        order_id=order.business_id,
        policy_version=policy_version,
        outcome="no_credit",
        decided_at=decided_at.astimezone(UTC),
        details={
            "reason_code": reason_code,
            "window_start": window_start.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "window_end": order.placed_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "eligible_click_count": 0,
        },
    )
    session.add(decision)
    session.flush([decision])


def _write_attribution_decision(
    session: Session,
    *,
    order: Order,
    policy_version: str,
    decided_at: datetime,
    eligible_events: list[MessageEvent],
    selected_event: MessageEvent,
) -> AttributionDecision:
    selected_schedule = _resolve_event_schedule(selected_event)
    if selected_schedule is None:
        raise InvalidDecisionInputError("selected click is missing a linked send schedule")

    decision = AttributionDecision(
        business_id=_stable_business_id("ATTRD", order.business_id, selected_event.business_id, policy_version),
        order_id=order.business_id,
        policy_version=policy_version,
        outcome="credited",
        decided_at=decided_at.astimezone(UTC),
        details={
            "reason_code": "last_eligible_click",
            "window_start": (order.placed_at - timedelta(days=7)).astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "window_end": order.placed_at.astimezone(UTC).isoformat().replace("+00:00", "Z"),
            "selected_message_event_id": selected_event.business_id,
            "selected_campaign_id": selected_schedule.campaign_id,
            "eligible_click_count": len(eligible_events),
        },
    )
    session.add(decision)
    session.flush([decision])

    for rank, event in enumerate(eligible_events, start=1):
        schedule = _resolve_event_schedule(event)
        if schedule is None:
            continue
        candidate = AttributionCandidate(
            business_id=_stable_business_id("ATTRC", decision.business_id, event.business_id, str(rank)),
            decision_id=decision.business_id,
            campaign_id=schedule.campaign_id,
            message_event_id=event.business_id,
            rank=rank,
            eligible=event.business_id == selected_event.business_id,
            reason="selected_click" if event.business_id == selected_event.business_id else "eligible_but_not_selected",
        )
        session.add(candidate)

    return decision


def _build_attribution(
    *,
    order: Order,
    decision: AttributionDecision,
    selected_event: MessageEvent,
    decided_at: datetime,
) -> Attribution:
    selected_schedule = _resolve_event_schedule(selected_event)
    if selected_schedule is None:
        raise InvalidDecisionInputError("selected click is missing a linked send schedule")

    return Attribution(
        business_id=_stable_business_id("ATTR", order.business_id, selected_event.business_id),
        order_id=order.business_id,
        decision_id=decision.business_id,
        campaign_id=selected_schedule.campaign_id,
        message_event_id=selected_event.business_id,
        credited_amount=None,
        currency_code=order.currency_code,
        created_at=decided_at.astimezone(UTC),
    )


def evaluate_order_attribution(
    session: Session,
    order: Order,
    *,
    policy_version: str = "click-last-touch-7d-v1",
    decided_at: datetime | None = None,
) -> Attribution | None:
    if order is None:
        raise InvalidDecisionInputError("order is required")
    if not order.business_id or not str(order.business_id).strip():
        raise InvalidDecisionInputError("order.business_id is required")
    if not order.customer_id or not str(order.customer_id).strip():
        raise InvalidDecisionInputError("order.customer_id is required")
    require_aware(order.placed_at, "order.placed_at")

    existing = _existing_canonical_attribution(session, order.business_id)
    if existing is not None:
        return existing

    window_start = order.placed_at - timedelta(days=7)
    eligible_events = _eligible_clicks_for_order(session, order)
    if not eligible_events:
        _write_no_credit_decision(
            session,
            order=order,
            policy_version=policy_version,
            decided_at=(decided_at or datetime.now(UTC)).astimezone(UTC),
            reason_code="no_eligible_click",
            window_start=window_start,
        )
        return None

    selected_event = eligible_events[0]
    decision_time = (decided_at or datetime.now(UTC)).astimezone(UTC)
    decision = _write_attribution_decision(
        session,
        order=order,
        policy_version=policy_version,
        decided_at=decision_time,
        eligible_events=eligible_events,
        selected_event=selected_event,
    )
    attribution = _build_attribution(
        order=order,
        decision=decision,
        selected_event=selected_event,
        decided_at=decision_time,
    )
    session.add(attribution)
    try:
        session.flush([attribution])
    except IntegrityError:
        session.rollback()
        recovered = _existing_canonical_attribution(session, order.business_id)
        if recovered is not None:
            return recovered
        raise
    return attribution
