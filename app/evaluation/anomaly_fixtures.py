from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class EvaluationAnomalyFinding:
    issue_type: str
    entity_type: str
    entity_business_id: str
    details: dict[str, object]


def detect_attribution_fixture_anomalies(
    evaluation_results: Mapping[str, Any],
) -> list[EvaluationAnomalyFinding]:
    fixtures = evaluation_results.get("anomaly_fixtures", {})
    if not isinstance(fixtures, Mapping):
        return []

    cases = fixtures.get("attribution_double_counted", [])
    if not isinstance(cases, list):
        return []

    findings: list[EvaluationAnomalyFinding] = []
    for case in cases:
        if not isinstance(case, Mapping):
            continue
        order_id = case.get("order_id")
        credits = case.get("credits")
        if not isinstance(order_id, str) or not order_id or not isinstance(credits, list):
            continue

        campaign_ids = sorted(
            {
                credit["campaign_id"]
                for credit in credits
                if isinstance(credit, Mapping)
                and isinstance(credit.get("campaign_id"), str)
                and credit["campaign_id"]
            }
        )
        if len(campaign_ids) < 2:
            continue

        findings.append(
            EvaluationAnomalyFinding(
                issue_type="attribution_double_counted",
                entity_type="order",
                entity_business_id=order_id,
                details={
                    "legacy_credit_count": len(credits),
                    "campaign_ids": campaign_ids,
                },
            )
        )

    return sorted(findings, key=lambda finding: finding.entity_business_id)