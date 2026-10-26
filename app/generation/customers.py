from datetime import timedelta

from sqlalchemy.orm import Session

from app.generation.config import GenerationConfig
from app.generation.ids import customer_id
from app.generation.randomness import rng_for
from app.generation.writer import insert_batches
from app.models import Consent, ConsentEvent, Customer


def generate_customers(
    session: Session,
    config: GenerationConfig,
    counts: dict[str, int],
) -> None:
    reference_time = config.reference_time
    insert_batches(
        session,
        Customer,
        (
            {
                "business_id": customer_id(index),
                "email": f"customer{index:06d}@example.test",
                "status": "active",
                "created_at": reference_time - timedelta(days=30 + index % 60),
            }
            for index in range(1, config.counts.customer_count + 1)
        ),
        batch_size=config.batch_size,
        counts=counts,
    )

    def consent_records():
        rates = dict(config.consent_basis_points)
        initial_time = reference_time - timedelta(days=90)
        updated_time = reference_time - timedelta(days=30)
        for customer_number in range(1, config.counts.customer_count + 1):
            customer_business_id = customer_id(customer_number)
            for channel in config.channels:
                channel_code = channel.upper()
                random_source = rng_for(config.seed, f"consent:{customer_business_id}:{channel}")
                state = "granted" if random_source.randrange(10_000) < rates.get(channel, 0) else "denied"
                consent_id = f"CONSENT-{customer_number:06d}-{channel_code}"
                yield {
                    "business_id": consent_id,
                    "customer_id": customer_business_id,
                    "channel": channel,
                    "state": state,
                    "updated_at": updated_time,
                }

    def consent_event_records():
        rates = dict(config.consent_basis_points)
        initial_time = reference_time - timedelta(days=90)
        updated_time = reference_time - timedelta(days=30)
        for customer_number in range(1, config.counts.customer_count + 1):
            customer_business_id = customer_id(customer_number)
            for channel in config.channels:
                channel_code = channel.upper()
                random_source = rng_for(config.seed, f"consent:{customer_business_id}:{channel}")
                final_state = "granted" if random_source.randrange(10_000) < rates.get(channel, 0) else "denied"
                events = (
                    (1, "consent_initialized", "unknown", initial_time),
                    (2, "consent_updated", final_state, updated_time),
                )
                for event_number, event_type, state, occurred_at in events:
                    event_id = f"CSE-{customer_number:06d}-{channel_code}-{event_number:02d}"
                    yield {
                        "business_id": event_id,
                        "customer_id": customer_business_id,
                        "channel": channel,
                        "event_type": event_type,
                        "state": state,
                        "source_system": "synthetic",
                        "source_event_key": event_id,
                        "occurred_at": occurred_at,
                        "recorded_at": occurred_at,
                    }

    insert_batches(
        session,
        Consent,
        consent_records(),
        batch_size=config.batch_size,
        counts=counts,
    )
    insert_batches(
        session,
        ConsentEvent,
        consent_event_records(),
        batch_size=config.batch_size,
        counts=counts,
    )