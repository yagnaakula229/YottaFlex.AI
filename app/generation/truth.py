from datetime import datetime

from sqlalchemy import insert
from sqlalchemy.orm import Session

from app.evaluation.models import EvaluationRun, GroundTruthLabel
from app.generation.config import GenerationConfig
from app.generation.ids import evaluation_run_id, indexed_id

CLEAN_BASELINE_LABELS = (
    "message_sent_after_opt_out",
    "cart_abandoned_after_purchase",
    "attribution_double_counted",
    "stale_cart_total_after_quantity_update",
)


def generate_truth_manifest(
    session: Session,
    config: GenerationConfig,
    generation_business_id: str,
    actual_counts: dict[str, int | str],
) -> str:
    run_business_id = evaluation_run_id(config)
    timestamp = config.reference_time
    session.execute(
        insert(EvaluationRun),
        [
            {
                "business_id": run_business_id,
                "generation_run_business_id": generation_business_id,
                "status": "completed",
                "started_at": timestamp,
                "finished_at": timestamp,
                "results": {
                    "profile": config.profile,
                    "clean_baseline": True,
                    "operational_counts": actual_counts,
                },
            }
        ],
    )
    session.execute(
        insert(GroundTruthLabel),
        [
            {
                "business_id": indexed_id("GT-BASELINE", index),
                "evaluation_run_id": run_business_id,
                "label_code": label_code,
                "entity_type": "dataset",
                "entity_business_id": generation_business_id,
                "expected": False,
                "label_payload": {"scope": "clean_baseline", "profile": config.profile},
                "recorded_at": timestamp,
            }
            for index, label_code in enumerate(CLEAN_BASELINE_LABELS, start=1)
        ],
    )
    return run_business_id