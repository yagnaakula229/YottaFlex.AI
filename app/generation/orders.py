from datetime import timedelta

from sqlalchemy.orm import Session

from app.generation.carts import _cart_facts
from app.generation.config import GenerationConfig
from app.generation.ids import order_id
from app.generation.writer import insert_batches
from app.models import Order


def generate_orders(
    session: Session,
    config: GenerationConfig,
    counts: dict[str, int],
) -> None:
    first_converted_cart = config.counts.abandoned_cart_count + 1
    last_converted_cart = first_converted_cart + config.counts.converted_cart_count

    def records():
        for order_number, cart_number in enumerate(range(first_converted_cart, last_converted_cart), start=1):
            cart_row = _cart_facts(cart_number, config)[0]
            yield {
                "business_id": order_id(order_number),
                "customer_id": cart_row["customer_id"],
                "cart_id": cart_row["business_id"],
                "status": "paid",
                "total_amount": cart_row["total_amount"],
                "currency_code": cart_row["currency_code"],
                "placed_at": cart_row["updated_at"] + timedelta(minutes=1),
            }

    insert_batches(
        session,
        Order,
        records(),
        batch_size=config.batch_size,
        counts=counts,
    )