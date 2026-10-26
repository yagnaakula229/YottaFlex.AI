from app.generation.config import GenerationConfig


def customer_id(index: int) -> str:
    return f"CUS-{index:06d}"


def cart_id(index: int) -> str:
    return f"CART-2026-{index:06d}"


def campaign_id(index: int) -> str:
    return f"CMP-2026-{index:06d}"


def order_id(index: int) -> str:
    return f"ORD-2026-{index:06d}"


def schedule_id(index: int) -> str:
    return f"SEND-2026-{index:06d}"


def generation_run_id(config: GenerationConfig) -> str:
    return f"GEN-{config.profile}-{config.configuration_hash[:20]}"


def evaluation_run_id(config: GenerationConfig) -> str:
    return f"EVAL-{config.profile}-{config.configuration_hash[:20]}"


def customer_for_cart(index: int, config: GenerationConfig) -> str:
    counts = config.counts
    if index <= counts.abandoned_cart_count + counts.converted_cart_count:
        customer_index = index
    else:
        customer_index = ((index - 1) % counts.customer_count) + 1
    return customer_id(customer_index)


def indexed_id(prefix: str, index: int, width: int = 6) -> str:
    return f"{prefix}-{index:0{width}d}"