from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import timedelta

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class RecoveryPolicy:
    version: str = "recovery-v1-provisional"
    inactivity_threshold: timedelta = timedelta(minutes=60)
    qualifying_cart_event_types: tuple[str, ...] = (
        "cart_created",
        "cart_activity",
        "cart_line_added",
        "cart_line_updated",
        "cart_line_removed",
    )
    purchase_blocking_statuses: tuple[str, ...] = ("pending", "paid", "refunded")
    qualifying_attempt_states: tuple[str, ...] = ("accepted",)
    frequency_cap_24h: int = 1
    frequency_cap_7d: int = 3
    conversion_window: timedelta = timedelta(days=7)
    selection_policy: str = "campaign-id-priority-template-id-v1"
    use_cart_updated_at_fallback: bool = True
    rolling_window_boundary: str = "(lower, upper]"

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ValueError("Recovery policy version cannot be empty")
        if self.inactivity_threshold.total_seconds() <= 0:
            raise ValueError("Inactivity threshold must be positive")
        if self.frequency_cap_24h < 0 or self.frequency_cap_7d < 0:
            raise ValueError("Frequency caps cannot be negative")
        if self.conversion_window.total_seconds() <= 0:
            raise ValueError("Conversion window must be positive")
        if self.selection_policy != "campaign-id-priority-template-id-v1":
            raise ValueError(f"Unsupported campaign selection policy: {self.selection_policy}")
        if self.rolling_window_boundary not in {"(lower, upper]", "[lower, upper]"}:
            raise ValueError(f"Unsupported frequency window boundary: {self.rolling_window_boundary}")

    @classmethod
    def from_settings(cls, settings: Settings | None = None) -> RecoveryPolicy:
        app_settings = settings or get_settings()
        return cls(
            version=app_settings.recovery_policy_version,
            inactivity_threshold=timedelta(minutes=app_settings.abandoned_cart_inactivity_minutes),
            qualifying_cart_event_types=app_settings.recovery_qualifying_cart_event_types,
            purchase_blocking_statuses=app_settings.recovery_purchase_blocking_statuses,
            qualifying_attempt_states=app_settings.recovery_qualifying_attempt_states,
            frequency_cap_24h=app_settings.recovery_frequency_cap_24h,
            frequency_cap_7d=app_settings.recovery_frequency_cap_7d,
            rolling_window_boundary=app_settings.recovery_rolling_window_boundary,
            conversion_window=timedelta(days=app_settings.recovery_conversion_window_days),
            selection_policy=app_settings.recovery_campaign_selection_policy,
            use_cart_updated_at_fallback=app_settings.recovery_use_cart_updated_at_fallback,
        )

    def as_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "inactivity_seconds": int(self.inactivity_threshold.total_seconds()),
            "qualifying_cart_event_types": list(self.qualifying_cart_event_types),
            "purchase_blocking_statuses": list(self.purchase_blocking_statuses),
            "qualifying_attempt_states": list(self.qualifying_attempt_states),
            "frequency_cap_24h": self.frequency_cap_24h,
            "frequency_cap_7d": self.frequency_cap_7d,
            "conversion_window_seconds": int(self.conversion_window.total_seconds()),
            "selection_policy": self.selection_policy,
            "use_cart_updated_at_fallback": self.use_cart_updated_at_fallback,
            "rolling_window_boundary": self.rolling_window_boundary,
        }

    @property
    def configuration_hash(self) -> str:
        serialized = json.dumps(self.as_dict(), sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()