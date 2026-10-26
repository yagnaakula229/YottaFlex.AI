from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Literal

from app.generation import DEFAULT_SEED, GENERATOR_VERSION

ProfileName = Literal["small", "scale"]
DEFAULT_REFERENCE_TIME = datetime(2026, 10, 22, tzinfo=UTC)
MAX_SEND_ATTEMPTS = 10_000


@dataclass(frozen=True)
class Profile:
    cart_count: int
    abandoned_cart_count: int
    converted_cart_count: int

    @property
    def customer_count(self) -> int:
        return (self.cart_count + 1) // 2


PROFILES: dict[ProfileName, Profile] = {
    "small": Profile(cart_count=100, abandoned_cart_count=40, converted_cart_count=10),
    "scale": Profile(
        cart_count=50_000,
        abandoned_cart_count=20_000,
        converted_cart_count=5_000,
    ),
}


@dataclass(frozen=True)
class GenerationConfig:
    profile: ProfileName
    reference_time: datetime = DEFAULT_REFERENCE_TIME
    seed: int = DEFAULT_SEED
    batch_size: int = 1_000
    inactivity_minutes: int = 60
    max_send_attempts: int = MAX_SEND_ATTEMPTS
    frequency_cap_per_24_hours: int = 1
    frequency_cap_per_7_days: int = 3
    channels: tuple[str, ...] = ("email", "sms")
    consent_basis_points: tuple[tuple[str, int], ...] = (("email", 7_500), ("sms", 5_500))
    send_channel: str = "email"
    currency_codes: tuple[str, ...] = ("USD",)
    unresolved_business_ids: tuple[str, ...] = ("MSG--01",)
    generator_version: str = GENERATOR_VERSION

    def __post_init__(self) -> None:
        if self.profile not in PROFILES:
            raise ValueError(f"Unknown generation profile: {self.profile}")
        if self.reference_time.tzinfo is None or self.reference_time.utcoffset() is None:
            raise ValueError("reference_time must be timezone-aware")
        if self.batch_size < 1:
            raise ValueError("batch_size must be positive")
        if self.max_send_attempts < 0:
            raise ValueError("max_send_attempts cannot be negative")
        if self.inactivity_minutes < 1:
            raise ValueError("inactivity_minutes must be positive")
        if self.send_channel not in self.channels:
            raise ValueError("send_channel must be included in channels")
        if not self.currency_codes:
            raise ValueError("At least one currency code is required")
        if any(len(currency) != 3 or not currency.isascii() or not currency.isupper() for currency in self.currency_codes):
            raise ValueError("Currency codes must be uppercase three-character strings")
        if any(not 0 <= basis_points <= 10_000 for _, basis_points in self.consent_basis_points):
            raise ValueError("Consent basis points must be between 0 and 10000")

    @property
    def counts(self) -> Profile:
        return PROFILES[self.profile]

    @property
    def requested_counts(self) -> dict[str, int]:
        return {
            "customers": self.counts.customer_count,
            "carts": self.counts.cart_count,
            "abandoned_carts": self.counts.abandoned_cart_count,
            "converted_carts": self.counts.converted_cart_count,
            "orders": self.counts.converted_cart_count,
            "max_send_attempts": min(self.max_send_attempts, MAX_SEND_ATTEMPTS, self.counts.abandoned_cart_count),
        }

    def as_dict(self) -> dict[str, object]:
        value = asdict(self)
        value["reference_time"] = self.reference_time.astimezone(UTC).isoformat()
        value["requested_counts"] = self.requested_counts
        return value

    @property
    def configuration_hash(self) -> str:
        serialized = canonical_json(self.as_dict())
        return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def canonical_json(value: object) -> str:
    import json

    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)