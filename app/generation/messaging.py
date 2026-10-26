from __future__ import annotations

import hashlib
from datetime import timedelta

from sqlalchemy import and_, func, outerjoin, select
from sqlalchemy.orm import Session

from app.generation.config import GenerationConfig
from app.generation.ids import campaign_id, indexed_id, schedule_id
from app.generation.randomness import rng_for
from app.generation.writer import insert_batches
from app.models import Cart, Consent, MessageEvent, Order, SendAttempt, SendSchedule


def schedule_idempotency_key(cart_business_id: str, campaign_business_id: str, config: GenerationConfig) -> str:
    material = "|".join(
        (
            cart_business_id,
            campaign_business_id,
            config.send_channel,
            config.configuration_hash,
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _abandoned_cart_query(config: GenerationConfig, *, require_consent: bool):
    query = select(Cart.business_id, Cart.customer_id).select_from(
        outerjoin(Cart, Order, Order.cart_id == Cart.business_id)
    )
    if require_consent:
        query = query.join(
            Consent,
            and_(
                Consent.customer_id == Cart.customer_id,
                Consent.channel == config.send_channel,
                Consent.state == "granted",
            ),
        )
    cutoff = config.reference_time - timedelta(minutes=config.inactivity_minutes)
    return (
        query.where(
            Cart.status == "abandoned",
            Cart.updated_at <= cutoff,
            Order.business_id.is_(None),
        )
        .order_by(Cart.business_id)
    )


def generate_sends(
    session: Session,
    config: GenerationConfig,
    counts: dict[str, int],
) -> None:
    candidate_count = session.scalar(
        select(func.count()).select_from(_abandoned_cart_query(config, require_consent=False).subquery())
    ) or 0
    consenting_count = session.scalar(
        select(func.count()).select_from(_abandoned_cart_query(config, require_consent=True).subquery())
    ) or 0
    counts["operationally_abandoned_carts"] = candidate_count
    counts["eligible_with_channel_consent"] = consenting_count
    counts["suppressed_no_channel_consent"] = candidate_count - consenting_count
    counts["suppressed_frequency_cap"] = 0

    max_attempts = min(
        config.max_send_attempts,
        config.requested_counts["max_send_attempts"],
        consenting_count,
    )
    counts["suppressed_send_attempt_limit"] = consenting_count - max_attempts
    candidates = session.execute(
        _abandoned_cart_query(config, require_consent=True).limit(max_attempts)
    ).yield_per(config.batch_size)

    def schedule_records():
        seen_customers: set[str] = set()
        emitted = 0
        for cart_business_id, customer_business_id in candidates:
            if customer_business_id in seen_customers:
                counts["suppressed_frequency_cap"] = counts.get("suppressed_frequency_cap", 0) + 1
                continue
            seen_customers.add(customer_business_id)
            emitted += 1
            random_source = rng_for(config.seed, f"send-attempt:{emitted}")
            failed_attempt = random_source.randrange(10_000) < 200
            campaign_business_id = campaign_id(((emitted - 1) % 3) + 1)
            scheduled_for = config.reference_time - timedelta(minutes=30) + timedelta(seconds=emitted % 1_200)
            yield {
                "business_id": schedule_id(emitted),
                "idempotency_key": schedule_idempotency_key(cart_business_id, campaign_business_id, config),
                "customer_id": customer_business_id,
                "cart_id": cart_business_id,
                "campaign_id": campaign_business_id,
                "channel": config.send_channel,
                "status": "failed" if failed_attempt else "sent",
                "scheduled_for": scheduled_for,
                "created_at": scheduled_for - timedelta(minutes=5),
            }
        counts["eligible_schedules"] = emitted

    schedules = list(schedule_records())
    insert_batches(
        session,
        SendSchedule,
        schedules,
        batch_size=config.batch_size,
        counts=counts,
    )

    def attempt_records():
        for sequence, schedule in enumerate(schedules, start=1):
            random_source = rng_for(config.seed, f"send-attempt:{sequence}")
            failed = random_source.randrange(10_000) < 200
            yield {
                "business_id": indexed_id("SATT-2026", sequence),
                "schedule_id": schedule["business_id"],
                "attempt_number": 1,
                "status": "failed" if failed else "accepted",
                "attempted_at": schedule["scheduled_for"] + timedelta(seconds=1),
                "provider_reference": None if failed else indexed_id("PROVIDER", sequence),
                "error_detail": "synthetic transient provider failure" if failed else None,
            }

    attempt_rows = list(attempt_records())
    counts["send_attempts_failed"] = sum(row["status"] == "failed" for row in attempt_rows)
    insert_batches(
        session,
        SendAttempt,
        attempt_rows,
        batch_size=config.batch_size,
        counts=counts,
    )

    def message_event_records():
        for sequence, attempt in enumerate(attempt_rows, start=1):
            if attempt["status"] != "accepted":
                continue
            random_source = rng_for(config.seed, f"message-engagement:{sequence}")
            base_time = attempt["attempted_at"]
            events = [("sent", base_time)]
            if random_source.randrange(10_000) < 9_700:
                delivered_at = base_time + timedelta(seconds=2)
                events.append(("delivered", delivered_at))
                if random_source.randrange(10_000) < 4_500:
                    opened_at = delivered_at + timedelta(minutes=5)
                    events.append(("opened", opened_at))
                    if random_source.randrange(10_000) < 2_000:
                        events.append(("clicked", opened_at + timedelta(seconds=30)))
            for event_number, (event_type, occurred_at) in enumerate(events, start=1):
                event_business_id = indexed_id(f"ME-{sequence:06d}", event_number)
                yield {
                    "business_id": event_business_id,
                    "send_attempt_id": attempt["business_id"],
                    "event_type": event_type,
                    "source_system": "synthetic-provider",
                    "source_event_key": event_business_id,
                    "occurred_at": occurred_at,
                    "recorded_at": occurred_at,
                    "payload": {"sequence": sequence},
                }

    insert_batches(
        session,
        MessageEvent,
        message_event_records(),
        batch_size=config.batch_size,
        counts=counts,
    )
    counts["send_attempts_accepted"] = sum(row["status"] == "accepted" for row in attempt_rows)