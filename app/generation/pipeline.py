from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app.db.base import Base
from app.evaluation.base import EvaluationBase
from app.generation import GENERATOR_VERSION
from app.generation.campaigns import generate_campaigns
from app.generation.carts import generate_carts
from app.generation.config import GenerationConfig
from app.generation.customers import generate_customers
from app.generation.export import hash_dataset
from app.generation.ids import generation_run_id
from app.generation.messaging import generate_sends
from app.generation.orders import generate_orders
from app.generation.sessions import generate_sessions
from app.generation.truth import generate_truth_manifest
from app.models import GenerationRun

GENERATION_ORDER = (
    "customers_and_consent",
    "sessions",
    "campaigns_templates_mappings",
    "carts_lines_events",
    "orders",
    "schedules_attempts_message_events",
    "evaluation_truth_labels",
    "generation_manifest",
)

INITIAL_ACTUAL_COUNTS = {
    "attribution": 0,
    "attribution_candidate": 0,
    "attribution_decision": 0,
    "audit_event": 0,
    "issue": 0,
}


@dataclass(frozen=True)
class GenerationSummary:
    generation_run_id: str
    configuration_hash: str
    dataset_sha256: str
    requested_counts: dict[str, int]
    actual_counts: dict[str, int | str]
    already_generated: bool = False


def _database_has_generated_rows(session: Session) -> bool:
    for metadata in (Base.metadata, EvaluationBase.metadata):
        for table in metadata.sorted_tables:
            if table.name in {"generation_run", "evaluation_run"}:
                continue
            if session.execute(select(1).select_from(table).limit(1)).first() is not None:
                return True
    return False


def _summary_from_manifest(manifest: GenerationRun, *, already_generated: bool) -> GenerationSummary:
    return GenerationSummary(
        generation_run_id=manifest.business_id,
        configuration_hash=manifest.configuration_hash,
        dataset_sha256=str(manifest.actual_counts["dataset_sha256"]),
        requested_counts=manifest.requested_counts,
        actual_counts=manifest.actual_counts,
        already_generated=already_generated,
    )


def generate_dataset(session: Session, config: GenerationConfig) -> GenerationSummary:
    manifest_business_id = generation_run_id(config)
    existing = session.get(GenerationRun, manifest_business_id)
    if existing is not None:
        current_hash = hash_dataset(session)
        expected_hash = str(existing.actual_counts["dataset_sha256"])
        if current_hash != expected_hash:
            raise RuntimeError("Existing generated rows do not match their manifest; use the guarded rebuild command.")
        return _summary_from_manifest(existing, already_generated=True)
    if _database_has_generated_rows(session):
        raise RuntimeError("The configured database is not empty; use the guarded rebuild command.")

    actual_counts: dict[str, int] = dict(INITIAL_ACTUAL_COUNTS)
    generate_customers(session, config, actual_counts)
    generate_sessions(session, config, actual_counts)
    generate_campaigns(session, config, actual_counts)
    generate_carts(session, config, actual_counts)
    generate_orders(session, config, actual_counts)
    generate_sends(session, config, actual_counts)

    evaluation_business_id = generate_truth_manifest(
        session,
        config,
        manifest_business_id,
        actual_counts,
    )
    actual_counts["evaluation_run"] = 1
    actual_counts["ground_truth_label"] = 4
    dataset_sha256 = hash_dataset(session)
    actual_counts["generation_run"] = 1
    actual_counts["dataset_sha256"] = dataset_sha256

    configuration: dict[str, Any] = {
        **config.as_dict(),
        "configuration_hash": config.configuration_hash,
        "generator_version": GENERATOR_VERSION,
        "actual_counts": actual_counts,
        "dataset_sha256": dataset_sha256,
        "evaluation_run_id": evaluation_business_id,
    }
    manifest_values = {
        "business_id": manifest_business_id,
        "seed": config.seed,
        "profile": config.profile,
        "configuration_hash": config.configuration_hash,
        "generator_version": GENERATOR_VERSION,
        "requested_counts": config.requested_counts,
        "actual_counts": actual_counts,
        "reference_timestamp": config.reference_time,
        "status": "completed",
        "scenario_as_of": config.reference_time,
        "started_at": config.reference_time,
        "finished_at": config.reference_time,
        "configuration": configuration,
    }
    session.execute(insert(GenerationRun), [manifest_values])
    return GenerationSummary(
        generation_run_id=manifest_business_id,
        configuration_hash=config.configuration_hash,
        dataset_sha256=dataset_sha256,
        requested_counts=config.requested_counts,
        actual_counts=actual_counts,
    )