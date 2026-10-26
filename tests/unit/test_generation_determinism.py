from datetime import UTC, datetime

import pytest

from app.generation.config import GenerationConfig
from app.generation.ids import (
    campaign_id,
    cart_id,
    customer_id,
    order_id,
    schedule_id,
)
from app.generation.config import GenerationConfig
from app.generation.randomness import rng_for
from app.generation.serialization import DatasetHasher, canonical_json
from app.generation.reset import validate_destructive_target


def test_supplied_business_ids_are_preserved() -> None:
    assert customer_id(1) == "CUS-000001"
    assert cart_id(1) == "CART-2026-000001"
    assert campaign_id(1) == "CMP-2026-000001"
    assert order_id(1) == "ORD-2026-000001"
    assert schedule_id(1) == "SEND-2026-000001"
    assert "MSG--01" in GenerationConfig(profile="small").unresolved_business_ids
    assert len("MSG--01") <= 64


def test_config_hash_and_namespaced_random_streams_are_reproducible() -> None:
    reference_time = datetime(2026, 10, 22, tzinfo=UTC)
    first = GenerationConfig(profile="small", reference_time=reference_time)
    second = GenerationConfig(profile="small", reference_time=reference_time)

    assert first.configuration_hash == second.configuration_hash
    first_stream = rng_for(first.seed, "customer:1")
    second_stream = rng_for(second.seed, "customer:1")
    assert [first_stream.random() for _ in range(3)] == [second_stream.random() for _ in range(3)]


def test_scale_profile_requests_documented_targets_and_send_cap() -> None:
    config = GenerationConfig(profile="scale")

    assert config.requested_counts["carts"] == 50_000
    assert config.requested_counts["abandoned_carts"] == 20_000
    assert config.requested_counts["max_send_attempts"] == 10_000


def test_canonical_export_hash_uses_stable_key_ordering() -> None:
    left = {"b": 2, "a": 1}
    right = {"a": 1, "b": 2}
    assert canonical_json(left) == canonical_json(right)

    first = DatasetHasher()
    first.add("public.customer", left)
    second = DatasetHasher()
    second.add("public.customer", right)
    assert first.hexdigest() == second.hexdigest()


def test_destructive_rebuild_requires_explicit_local_development_target() -> None:
    local_url = "postgresql+psycopg://user:pass@localhost:5432/yottaflex_test"
    assert validate_destructive_target(local_url, "development", True) == "yottaflex_test"

    for database_url, environment, confirmed in (
        (local_url, "production", True),
        (local_url, "development", False),
        (local_url.replace("localhost", "db.example.test"), "development", True),
        (local_url.replace("yottaflex_test", "customer_data"), "development", True),
    ):
        with pytest.raises(PermissionError):
            validate_destructive_target(database_url, environment, confirmed)