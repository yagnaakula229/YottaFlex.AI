from datetime import timedelta

from sqlalchemy.orm import Session

from app.generation.config import GenerationConfig
from app.generation.ids import customer_id, indexed_id
from app.generation.randomness import rng_for
from app.generation.writer import insert_batches
from app.models import CustomerSession


def generate_sessions(
    session: Session,
    config: GenerationConfig,
    counts: dict[str, int],
) -> None:
    reference_time = config.reference_time

    def records():
        sequence = 0
        for customer_number in range(1, config.counts.customer_count + 1):
            random_source = rng_for(config.seed, f"sessions:{customer_number}")
            session_count = random_source.randint(1, 3)
            for session_number in range(session_count):
                sequence += 1
                started_at = reference_time - timedelta(
                    days=random_source.randint(1, 60),
                    hours=random_source.randint(0, 23),
                    minutes=random_source.randint(0, 59),
                )
                ended_at = started_at + timedelta(minutes=random_source.randint(1, 45))
                yield {
                    "business_id": indexed_id("SES-2026", sequence),
                    "customer_id": customer_id(customer_number),
                    "started_at": started_at,
                    "ended_at": ended_at,
                    "attributes": {"sequence": session_number + 1, "source": "synthetic"},
                }

    insert_batches(
        session,
        CustomerSession,
        records(),
        batch_size=config.batch_size,
        counts=counts,
    )