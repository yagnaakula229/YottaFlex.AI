from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.evaluation.base import EvaluationBase


class EvaluationRun(EvaluationBase):
    __tablename__ = "evaluation_run"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'completed', 'failed')", name="status_valid"),
        CheckConstraint("finished_at IS NULL OR finished_at >= started_at", name="finished_after_started"),
        Index("ix_evaluation_run_status_started", "status", "started_at"),
    )

    business_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    generation_run_business_id: Mapped[str | None] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    results: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)

    labels: Mapped[list[GroundTruthLabel]] = relationship(back_populates="evaluation_run")


class GroundTruthLabel(EvaluationBase):
    __tablename__ = "ground_truth_label"
    __table_args__ = (
        CheckConstraint(
            "label_code IN ('message_sent_after_opt_out', 'cart_abandoned_after_purchase', "
            "'attribution_double_counted', 'stale_cart_total_after_quantity_update')",
            name="label_code_valid",
        ),
        UniqueConstraint(
            "evaluation_run_id", "label_code", "entity_type", "entity_business_id", name="uq_ground_truth_label_case"
        ),
        Index("ix_ground_truth_label_code", "label_code", "entity_type", "entity_business_id"),
    )

    business_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    evaluation_run_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("evaluation.evaluation_run.business_id", name="fk_ground_truth_label_evaluation_run"),
        nullable=False,
    )
    label_code: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_business_id: Mapped[str] = mapped_column(String(64), nullable=False)
    expected: Mapped[bool] = mapped_column(nullable=False)
    label_payload: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    evaluation_run: Mapped[EvaluationRun] = relationship(back_populates="labels")