from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.models import (
    Campaign,
    CampaignTemplate,
    Customer,
    MessageTemplate,
    RecoveryDecision,
    SendAttempt,
    SendSchedule,
)
from app.services.recovery.abandonment import AbandonmentEvaluation, evaluate_cart_abandonment
from app.services.recovery.consent import ConsentResolution, resolve_effective_consent
from app.services.recovery.decisions import record_decision, require_aware
from app.services.recovery.errors import InvalidDecisionInputError, RecoveryNotFoundError
from app.services.recovery.policy import RecoveryPolicy


@dataclass(frozen=True)
class CampaignSelection:
    campaign_id: str
    template_id: str
    priority: int


@dataclass(frozen=True)
class FrequencyCapEvaluation:
    allowed: bool
    reason_code: str | None
    triggered_window: str | None
    count_24h: int
    count_7d: int
    lower_bound_24h: datetime
    lower_bound_7d: datetime
    upper_bound: datetime
    window_boundary: str

    def evidence(self) -> dict[str, object]:
        return {
            "qualifying_attempt_states": [],
            "count_24h": self.count_24h,
            "count_7d": self.count_7d,
            "triggered_window": self.triggered_window,
            "cap_24h": None,
            "cap_7d": None,
            "window_boundary": self.window_boundary,
            "window_24h": [self.lower_bound_24h.isoformat(), self.upper_bound.isoformat()],
            "window_7d": [self.lower_bound_7d.isoformat(), self.upper_bound.isoformat()],
        }


@dataclass(frozen=True)
class EligibilityEvaluation:
    eligible: bool
    reason_code: str | None
    decision: RecoveryDecision
    abandonment: AbandonmentEvaluation
    consent: ConsentResolution | None
    frequency: FrequencyCapEvaluation | None
    selection: CampaignSelection | None


def evaluate_frequency_caps(
    session: Session,
    *,
    customer_id: str,
    channel: str,
    evaluated_at: datetime,
    policy: RecoveryPolicy,
) -> FrequencyCapEvaluation:
    require_aware(evaluated_at, "evaluated_at")
    lower_bound_24h = evaluated_at - timedelta(hours=24)
    lower_bound_7d = evaluated_at - timedelta(days=7)

    def count_since(lower_bound: datetime) -> int:
        lower_bound_clause = (
            SendAttempt.attempted_at >= lower_bound
            if policy.rolling_window_boundary == "[lower, upper]"
            else SendAttempt.attempted_at > lower_bound
        )
        return int(
            session.scalar(
                select(func.count(SendAttempt.business_id))
                .select_from(SendAttempt)
                .join(SendSchedule, SendSchedule.business_id == SendAttempt.schedule_id)
                .where(
                    SendSchedule.customer_id == customer_id,
                    SendSchedule.channel == channel,
                    SendAttempt.status.in_(policy.qualifying_attempt_states),
                    lower_bound_clause,
                    SendAttempt.attempted_at <= evaluated_at,
                )
            )
            or 0
        )

    count_24h = count_since(lower_bound_24h)
    count_7d = count_since(lower_bound_7d)
    reason_code = None
    triggered_window = None
    if count_24h >= policy.frequency_cap_24h:
        reason_code = "FREQUENCY_CAP"
        triggered_window = "24h"
    elif count_7d >= policy.frequency_cap_7d:
        reason_code = "FREQUENCY_CAP"
        triggered_window = "7d"

    return FrequencyCapEvaluation(
        allowed=reason_code is None,
        reason_code=reason_code,
        triggered_window=triggered_window,
        count_24h=count_24h,
        count_7d=count_7d,
        lower_bound_24h=lower_bound_24h,
        lower_bound_7d=lower_bound_7d,
        upper_bound=evaluated_at,
        window_boundary=policy.rolling_window_boundary,
    )


def select_campaign_template(
    session: Session,
    *,
    channel: str,
    evaluated_at: datetime,
) -> CampaignSelection | None:
    require_aware(evaluated_at, "evaluated_at")
    row = session.execute(
        select(Campaign.business_id, CampaignTemplate.priority, MessageTemplate.business_id)
        .join(CampaignTemplate, CampaignTemplate.campaign_id == Campaign.business_id)
        .join(MessageTemplate, MessageTemplate.business_id == CampaignTemplate.template_id)
        .where(
            Campaign.status == "active",
            Campaign.created_at <= evaluated_at,
            MessageTemplate.status == "active",
            MessageTemplate.created_at <= evaluated_at,
            MessageTemplate.channel == channel,
            func.length(func.trim(MessageTemplate.content)) > 0,
        )
        .order_by(Campaign.business_id, CampaignTemplate.priority, MessageTemplate.business_id)
        .limit(1)
    ).first()
    if row is None:
        return None
    return CampaignSelection(campaign_id=row[0], priority=row[1], template_id=row[2])


def evaluate_customer_channel_eligibility(
    session: Session,
    *,
    cart_id: str,
    channel: str,
    evaluated_at: datetime,
    policy: RecoveryPolicy | None = None,
) -> EligibilityEvaluation:
    require_aware(evaluated_at, "evaluated_at")
    if not channel.strip():
        raise InvalidDecisionInputError("channel cannot be empty")
    effective_policy = policy or RecoveryPolicy.from_settings()
    abandonment = evaluate_cart_abandonment(
        session,
        cart_id=cart_id,
        evaluated_at=evaluated_at,
        policy=effective_policy,
    )
    customer = session.get(Customer, abandonment.decision.customer_id)
    if customer is None:
        raise RecoveryNotFoundError(f"Customer not found: {abandonment.decision.customer_id}")

    evidence: dict[str, Any] = {
        "abandonment_decision_id": abandonment.decision.business_id,
        "customer_status": customer.status,
    }
    consent: ConsentResolution | None = None
    frequency: FrequencyCapEvaluation | None = None
    selection: CampaignSelection | None = None
    reason_code: str | None = None

    if not abandonment.eligible:
        reason_code = abandonment.reason_code or "cart_ineligible"
    elif customer.status != "active":
        reason_code = "customer_inactive"
    else:
        consent = resolve_effective_consent(
            session,
            customer_id=customer.business_id,
            channel=channel,
            at=evaluated_at,
        )
        evidence["consent"] = {
            "state": consent.state,
            "allowed": consent.allowed,
            "source": consent.source,
            "event_id": consent.event_id,
            "effective_at": consent.effective_at.isoformat() if consent.effective_at else None,
            "reason_code": consent.reason_code,
        }
        if not consent.allowed:
            reason_code = consent.reason_code or "consent_not_granted"

    if reason_code is None:
        frequency = evaluate_frequency_caps(
            session,
            customer_id=customer.business_id,
            channel=channel,
            evaluated_at=evaluated_at,
            policy=effective_policy,
        )
        evidence["frequency_cap"] = {
            **frequency.evidence(),
            "qualifying_attempt_states": list(effective_policy.qualifying_attempt_states),
            "cap_24h": effective_policy.frequency_cap_24h,
            "cap_7d": effective_policy.frequency_cap_7d,
        }
        if not frequency.allowed:
            reason_code = frequency.reason_code

    if reason_code is None:
        selection = select_campaign_template(session, channel=channel, evaluated_at=evaluated_at)
        if selection is None:
            reason_code = "NO_CAMPAIGN_TEMPLATE"
        else:
            evidence["campaign_selection"] = {
                "campaign_id": selection.campaign_id,
                "template_id": selection.template_id,
                "priority": selection.priority,
                "selection_policy": effective_policy.selection_policy,
            }

    decision = record_decision(
        session,
        decision_type="eligibility",
        cart_id=cart_id,
        customer_id=customer.business_id,
        channel=channel,
        campaign_id=selection.campaign_id if selection else None,
        template_id=selection.template_id if selection else None,
        evaluated_at=evaluated_at,
        policy=effective_policy,
        outcome="eligible" if reason_code is None else "suppressed",
        reason_code=reason_code,
        evidence=evidence,
    )
    return EligibilityEvaluation(
        eligible=reason_code is None,
        reason_code=reason_code,
        decision=decision,
        abandonment=abandonment,
        consent=consent,
        frequency=frequency,
        selection=selection,
    )