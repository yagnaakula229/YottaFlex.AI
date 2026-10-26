from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class GenerationRun(Base):
    __tablename__ = "generation_run"
    __table_args__ = (
        CheckConstraint("status IN ('running', 'completed', 'failed')", name="status_valid"),
        CheckConstraint("finished_at IS NULL OR finished_at >= started_at", name="finished_after_started"),
        Index("ix_generation_run_status_started", "status", "started_at"),
    )

    business_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    seed: Mapped[int] = mapped_column(Integer, nullable=False)
    profile: Mapped[str] = mapped_column(String(16), nullable=False)
    configuration_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    generator_version: Mapped[str] = mapped_column(String(32), nullable=False)
    requested_counts: Mapped[dict[str, int]] = mapped_column(JSONB, nullable=False)
    actual_counts: Mapped[dict[str, int | str]] = mapped_column(JSONB, nullable=False)
    reference_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    scenario_as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    configuration: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)

    issues: Mapped[list[Issue]] = relationship(back_populates="generation_run")