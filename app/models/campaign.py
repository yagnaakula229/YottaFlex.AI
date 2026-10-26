from __future__ import annotations

from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Index, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


class Campaign(Base):
    __tablename__ = "campaign"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'active', 'paused', 'ended')", name="status_valid"),
        Index("ix_campaign_status", "status"),
    )

    business_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    template_links: Mapped[list[CampaignTemplate]] = relationship(back_populates="campaign")
    schedules: Mapped[list[SendSchedule]] = relationship(back_populates="campaign")


class MessageTemplate(Base):
    __tablename__ = "message_template"
    __table_args__ = (
        CheckConstraint("status IN ('draft', 'active', 'archived')", name="status_valid"),
        CheckConstraint("length(channel) > 0", name="channel_not_empty"),
        Index("ix_message_template_channel_status", "channel", "status"),
    )

    business_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    channel: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    campaign_links: Mapped[list[CampaignTemplate]] = relationship(back_populates="template")


class CampaignTemplate(Base):
    __tablename__ = "campaign_template"
    __table_args__ = (
        UniqueConstraint("campaign_id", "template_id", name="uq_campaign_template_pair"),
        UniqueConstraint("campaign_id", "priority", name="uq_campaign_template_priority"),
        CheckConstraint("priority >= 0", name="priority_nonnegative"),
    )

    business_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("campaign.business_id", name="fk_campaign_template_campaign"), nullable=False
    )
    template_id: Mapped[str] = mapped_column(
        String(64),
        ForeignKey("message_template.business_id", name="fk_campaign_template_template"),
        nullable=False,
    )
    priority: Mapped[int] = mapped_column(Integer, nullable=False)

    campaign: Mapped[Campaign] = relationship(back_populates="template_links")
    template: Mapped[MessageTemplate] = relationship(back_populates="campaign_links")