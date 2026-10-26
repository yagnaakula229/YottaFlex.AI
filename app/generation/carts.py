from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy.orm import Session

from app.generation.config import GenerationConfig
from app.generation.ids import cart_id, customer_for_cart, indexed_id
from app.generation.randomness import rng_for
from app.generation.writer import insert_batches
from app.models import Cart, CartEvent, CartLine


def _cart_facts(index: int, config: GenerationConfig):
    random_source = rng_for(config.seed, f"cart:{index}")
    reference_time = config.reference_time
    profile = config.counts
    created_at = reference_time - timedelta(
        days=random_source.randint(2, 90),
        hours=random_source.randint(0, 23),
    )

    is_abandoned = index <= profile.abandoned_cart_count
    is_converted = profile.abandoned_cart_count < index <= (
        profile.abandoned_cart_count + profile.converted_cart_count
    )
    if is_abandoned:
        status = "abandoned"
        updated_at = reference_time - timedelta(
            minutes=config.inactivity_minutes + random_source.randint(1, 240)
        )
    elif is_converted:
        status = "converted"
        updated_at = reference_time - timedelta(hours=random_source.randint(1, 48))
    else:
        status = "open"
        updated_at = reference_time - timedelta(
            minutes=random_source.randint(0, config.inactivity_minutes - 1)
        )

    line_count = random_source.randint(1, 3)
    item_numbers = random_source.sample(range(1, 101), line_count)
    currency_code = config.currency_codes[(index - 1) % len(config.currency_codes)]
    lines: list[dict[str, object]] = []
    cart_total = Decimal("0.0000")
    for line_number, item_number in enumerate(item_numbers, start=1):
        quantity = random_source.randint(1, 4)
        unit_price = Decimal(random_source.randint(100, 25_000)) / Decimal(100)
        line_total = (unit_price * quantity).quantize(Decimal("0.0001"))
        cart_total += line_total
        lines.append(
            {
                "business_id": indexed_id(f"CL-{index:06d}", line_number),
                "cart_id": cart_id(index),
                "item_key": f"SKU-{item_number:04d}",
                "quantity": quantity,
                "unit_price": unit_price,
                "line_total": line_total,
                "currency_code": currency_code,
                "attributes": {"catalog_item_number": item_number},
            }
        )

    cart_row = {
        "business_id": cart_id(index),
        "customer_id": customer_for_cart(index, config),
        "status": status,
        "total_amount": cart_total,
        "currency_code": currency_code,
        "created_at": created_at,
        "updated_at": updated_at,
    }
    event_rows = [
        {
            "business_id": indexed_id(f"CE-{index:06d}", 1),
            "cart_id": cart_id(index),
            "event_type": "cart_created",
            "source_system": "synthetic-storefront",
            "source_event_key": indexed_id(f"CE-{index:06d}", 1),
            "occurred_at": created_at,
            "recorded_at": created_at,
            "payload": {"status": "open"},
        },
        {
            "business_id": indexed_id(f"CE-{index:06d}", 2),
            "cart_id": cart_id(index),
            "event_type": (
                "cart_converted"
                if is_converted
                else "cart_abandoned"
                if is_abandoned
                else "cart_activity"
            ),
            "source_system": "synthetic-storefront",
            "source_event_key": indexed_id(f"CE-{index:06d}", 2),
            "occurred_at": updated_at,
            "recorded_at": updated_at,
            "payload": {"status": status},
        },
    ]
    return cart_row, lines, event_rows


def generate_carts(
    session: Session,
    config: GenerationConfig,
    counts: dict[str, int],
) -> None:
    cart_range = range(1, config.counts.cart_count + 1)
    insert_batches(
        session,
        Cart,
        (_cart_facts(index, config)[0] for index in cart_range),
        batch_size=config.batch_size,
        counts=counts,
    )
    insert_batches(
        session,
        CartLine,
        (line for index in cart_range for line in _cart_facts(index, config)[1]),
        batch_size=config.batch_size,
        counts=counts,
    )
    insert_batches(
        session,
        CartEvent,
        (event for index in cart_range for event in _cart_facts(index, config)[2]),
        batch_size=config.batch_size,
        counts=counts,
    )