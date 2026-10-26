from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import RecoveryDecision
from app.services.recovery.errors import InvalidDecisionInputError
from app.services.recovery.policy import RecoveryPolicy

DecisionType = Literal["abandonment", "eligibility"]


def require_aware(value: datetime, field_name: str) -> None:
    if value.tzinfo is None or value.utcoffset() is None:
        raise InvalidDecisionInputError(f"{field_name} must be timezone-aware")


def record_decision(
    session: Session,
    *,
    decision_type: DecisionType,
    cart_id: str,
    customer_id: str,
    channel: str,
    evaluated_at: datetime,
    policy: RecoveryPolicy,
    outcome: str,
    reason_code: str | None,
    evidence: dict[str, Any],
    campaign_id: str | None = None,
    template_id: str | None = None,
) -> RecoveryDecision:
    require_aware(evaluated_at, "evaluated_at")
    decision = RecoveryDecision(
        business_id=f"RDEC-{uuid4().hex}",
        decision_type=decision_type,
        cart_id=cart_id,
        customer_id=customer_id,
        channel=channel,
        campaign_id=campaign_id,
        template_id=template_id,
        outcome=outcome,
        reason_code=reason_code,
        evaluated_at=evaluated_at,
        policy_version=policy.version,
        configuration_hash=policy.configuration_hash,
        evidence=evidence,
    )
    session.add(decision)
    session.flush([decision])
    return decision