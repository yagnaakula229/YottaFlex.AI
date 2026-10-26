from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Issue(Base):
    __tablename__ = "issue"
    __table_args__ = (
        CheckConstraint(
            "issue_type IN ('message_sent_after_opt_out', 'cart_abandoned_after_purchase', "
            "'attribution_double_counted', 'stale_cart_total_after_quantity_update')",
            name="issue_type_valid",
        ),
        CheckConstraint("status IN ('open', 'acknowledged', 'resolved', 'false_positive')", name="status_valid"),
        Index("ix_issue_status_detected", "status", "detected_at"),
        Index("ix_issue_target", "entity_type", "entity_business_id"),
    )

    business_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    generation_run_id: Mapped[str | None] = mapped_column(
        String(64), ForeignKey("generation_run.business_id", name="fk_issue_generation_run")
    )
    issue_type: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_business_id: Mapped[str] = mapped_column(String(64), nullable=False)
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    details: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    generation_run: Mapped[GenerationRun | None] = relationship(back_populates="issues")


class AuditEvent(Base):
    __tablename__ = "audit_event"
    __table_args__ = (
        Index("ix_audit_event_target_occurred", "entity_type", "entity_business_id", "occurred_at"),
        Index("ix_audit_event_actor_occurred", "actor_id", "occurred_at"),
    )

    business_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_business_id: Mapped[str] = mapped_column(String(64), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    actor_id: Mapped[str | None] = mapped_column(String(128))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    details: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)