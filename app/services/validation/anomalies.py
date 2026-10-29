from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    Attribution,
    Cart,
    CartEvent,
    CartLine,
    MessageEvent,
    Order,
    SendAttempt,
    SendSchedule,
)
from app.services.recovery.consent import resolve_effective_consent


@dataclass(frozen=True)
class AnomalyFinding:
    issue_type: str
    entity_type: str
    entity_business_id: str
    details: dict[str, object]


def detect_operational_anomalies(session: Session) -> list[AnomalyFinding]:
    findings: list[AnomalyFinding] = []

    sent_events = session.execute(
        select(MessageEvent, SendSchedule)
        .join(SendAttempt, SendAttempt.business_id == MessageEvent.send_attempt_id)
        .join(SendSchedule, SendSchedule.business_id == SendAttempt.schedule_id)
        .where(MessageEvent.event_type == "sent")
        .order_by(MessageEvent.business_id)
    ).all()
    for event, schedule in sent_events:
        consent = resolve_effective_consent(
            session,
            customer_id=schedule.customer_id,
            channel=schedule.channel,
            at=event.occurred_at,
        )
        if consent.state == "denied":
            findings.append(
                AnomalyFinding(
                    issue_type="message_sent_after_opt_out",
                    entity_type="message_event",
                    entity_business_id=event.business_id,
                    details={"schedule_id": schedule.business_id, "consent_event_id": consent.event_id},
                )
            )

    abandoned_after_order = session.execute(
        select(Cart.business_id, Order.business_id, CartEvent.business_id)
        .join(Order, Order.cart_id == Cart.business_id)
        .join(CartEvent, CartEvent.cart_id == Cart.business_id)
        .where(
            Cart.status == "abandoned",
            CartEvent.event_type == "cart_abandoned",
            CartEvent.occurred_at >= Order.placed_at,
        )
        .order_by(Cart.business_id, CartEvent.business_id)
    ).all()
    findings.extend(
        AnomalyFinding(
            issue_type="cart_abandoned_after_purchase",
            entity_type="cart",
            entity_business_id=cart_id,
            details={"order_id": order_id, "cart_event_id": event_id},
        )
        for cart_id, order_id, event_id in abandoned_after_order
    )

    double_credits = session.execute(
        select(Attribution.order_id, func.count(Attribution.business_id))
        .group_by(Attribution.order_id)
        .having(func.count(Attribution.business_id) > 1)
        .order_by(Attribution.order_id)
    ).all()
    findings.extend(
        AnomalyFinding(
            issue_type="attribution_double_counted",
            entity_type="order",
            entity_business_id=order_id,
            details={"canonical_credit_count": count},
        )
        for order_id, count in double_credits
    )

    expected_totals = func.coalesce(
        func.sum(func.round(CartLine.unit_price * CartLine.quantity, 4)),
        0,
    )
    stale_totals = session.execute(
        select(Cart.business_id, Cart.total_amount, expected_totals)
        .outerjoin(CartLine, CartLine.cart_id == Cart.business_id)
        .group_by(Cart.business_id, Cart.total_amount)
        .having(Cart.total_amount != expected_totals)
        .order_by(Cart.business_id)
    ).all()
    findings.extend(
        AnomalyFinding(
            issue_type="stale_cart_total_after_quantity_update",
            entity_type="cart",
            entity_business_id=cart_id,
            details={"stored_total": str(stored_total), "expected_total": str(expected_total)},
        )
        for cart_id, stored_total, expected_total in stale_totals
    )

    return sorted(findings, key=lambda finding: (finding.issue_type, finding.entity_business_id))