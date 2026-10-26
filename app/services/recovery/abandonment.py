from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Cart, CartEvent, CartLine, Order, RecoveryDecision
from app.services.recovery.decisions import record_decision, require_aware
from app.services.recovery.errors import RecoveryNotFoundError
from app.services.recovery.policy import RecoveryPolicy


@dataclass(frozen=True)
class AbandonmentEvaluation:
    eligible: bool
    reason_code: str | None
    decision: RecoveryDecision
    evidence: dict[str, object]


def _evaluate_cart(session: Session, cart: Cart, evaluated_at: datetime, policy: RecoveryPolicy):
    evidence: dict[str, object] = {
        "cart_status": cart.status,
        "inactivity_threshold_seconds": int(policy.inactivity_threshold.total_seconds()),
    }

    purchase = session.execute(
        select(Order.business_id, Order.status)
        .where(Order.cart_id == cart.business_id, Order.status.in_(policy.purchase_blocking_statuses))
        .order_by(Order.placed_at, Order.business_id)
        .limit(1)
    ).first()
    if purchase is not None:
        evidence["blocking_order_id"] = purchase.business_id
        evidence["blocking_order_status"] = purchase.status
        return False, "prior_purchase", evidence

    if cart.status not in {"open", "abandoned"}:
        return False, "cart_not_open", evidence

    lines = session.scalars(
        select(CartLine).where(CartLine.cart_id == cart.business_id).order_by(CartLine.business_id)
    ).all()
    if not lines:
        return False, "empty_cart", {**evidence, "line_count": 0}

    line_total_sum = Decimal("0.0000")
    currencies: set[str] = set()
    for line in lines:
        currencies.add(line.currency_code.strip())
        if line.quantity <= 0:
            return False, "invalid_cart_quantity", {**evidence, "line_id": line.business_id}
        expected_line_total = (line.unit_price * line.quantity).quantize(Decimal("0.0001"))
        if line.line_total != expected_line_total:
            return False, "stale_cart_line_total", {
                **evidence,
                "line_id": line.business_id,
                "expected_line_total": format(expected_line_total, "f"),
                "stored_line_total": format(line.line_total, "f"),
            }
        line_total_sum += line.line_total

    evidence["line_count"] = len(lines)
    evidence["line_total_sum"] = format(line_total_sum, "f")
    evidence["cart_total"] = format(cart.total_amount, "f")
    if len(currencies) != 1 or next(iter(currencies)) != cart.currency_code.strip():
        evidence["line_currencies"] = sorted(currencies)
        return False, "cart_currency_mismatch", evidence
    if line_total_sum != cart.total_amount:
        return False, "stale_cart_total", evidence

    qualifying_event = session.scalar(
        select(CartEvent)
        .where(
            CartEvent.cart_id == cart.business_id,
            CartEvent.event_type.in_(policy.qualifying_cart_event_types),
            CartEvent.occurred_at <= evaluated_at,
        )
        .order_by(CartEvent.occurred_at.desc(), CartEvent.business_id.desc())
        .limit(1)
    )
    if qualifying_event is None:
        return False, "no_qualifying_cart_activity", evidence

    last_activity_at = qualifying_event.occurred_at
    used_projection_fallback = False
    if policy.use_cart_updated_at_fallback and last_activity_at < cart.updated_at <= evaluated_at:
        last_activity_at = cart.updated_at
        used_projection_fallback = True

    cutoff = evaluated_at - policy.inactivity_threshold
    evidence.update(
        {
            "last_activity_at": last_activity_at.isoformat(),
            "last_activity_event_id": qualifying_event.business_id,
            "cart_updated_at_fallback_used": used_projection_fallback,
            "inactivity_cutoff": cutoff.isoformat(),
        }
    )
    if last_activity_at > evaluated_at:
        return False, "future_cart_activity", evidence
    if last_activity_at > cutoff:
        return False, "cart_not_inactive_long_enough", evidence
    return True, None, evidence


def evaluate_cart_abandonment(
    session: Session,
    *,
    cart_id: str,
    evaluated_at: datetime,
    policy: RecoveryPolicy | None = None,
) -> AbandonmentEvaluation:
    require_aware(evaluated_at, "evaluated_at")
    effective_policy = policy or RecoveryPolicy.from_settings()
    cart = session.get(Cart, cart_id)
    if cart is None:
        raise RecoveryNotFoundError(f"Cart not found: {cart_id}")

    eligible, reason_code, evidence = _evaluate_cart(session, cart, evaluated_at, effective_policy)
    decision = record_decision(
        session,
        decision_type="abandonment",
        cart_id=cart.business_id,
        customer_id=cart.customer_id,
        channel="*",
        evaluated_at=evaluated_at,
        policy=effective_policy,
        outcome="eligible" if eligible else "suppressed",
        reason_code=reason_code,
        evidence=evidence,
    )
    return AbandonmentEvaluation(eligible, reason_code, decision, evidence)