from datetime import timedelta

from sqlalchemy.orm import Session

from app.generation.config import GenerationConfig
from app.generation.ids import campaign_id, indexed_id
from app.generation.writer import insert_batches
from app.models import Campaign, CampaignTemplate, MessageTemplate

TEMPLATE_CONTENT = (
    "Your cart is waiting. Continue when convenient.",
    "Items are still in your cart. Revisit them at your convenience.",
    "A reminder about the items you chose.",
    "Your saved items are ready when you are.",
    "Take another look at your recent cart.",
    "Your shopping session is ready to continue.",
)


def generate_campaigns(
    session: Session,
    config: GenerationConfig,
    counts: dict[str, int],
) -> None:
    created_at = config.reference_time - timedelta(days=30)
    campaign_count = 3
    templates_per_campaign = 2
    template_count = campaign_count * templates_per_campaign

    insert_batches(
        session,
        Campaign,
        (
            {
                "business_id": campaign_id(index),
                "name": f"Synthetic recovery campaign {index}",
                "status": "active",
                "created_at": created_at,
            }
            for index in range(1, campaign_count + 1)
        ),
        batch_size=config.batch_size,
        counts=counts,
    )
    insert_batches(
        session,
        MessageTemplate,
        (
            {
                "business_id": indexed_id("TPL-2026", index),
                "name": f"Synthetic template {index}",
                "channel": config.channels[(index - 1) % len(config.channels)],
                "status": "active",
                "content": TEMPLATE_CONTENT[(index - 1) % len(TEMPLATE_CONTENT)],
                "created_at": created_at,
            }
            for index in range(1, template_count + 1)
        ),
        batch_size=config.batch_size,
        counts=counts,
    )
    insert_batches(
        session,
        CampaignTemplate,
        (
            {
                "business_id": indexed_id("CMP-TPL-2026", (campaign_number - 1) * templates_per_campaign + priority + 1),
                "campaign_id": campaign_id(campaign_number),
                "template_id": indexed_id(
                    "TPL-2026", (campaign_number - 1) * templates_per_campaign + priority + 1
                ),
                "priority": priority,
            }
            for campaign_number in range(1, campaign_count + 1)
            for priority in range(templates_per_campaign)
        ),
        batch_size=config.batch_size,
        counts=counts,
    )