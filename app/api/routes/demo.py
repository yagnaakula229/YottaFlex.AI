from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

router = APIRouter(prefix="/api/demo", tags=["demo"])


@router.get("/summary")
def summary() -> dict[str, object]:
    """Return a synthetic dashboard payload for demo purposes.

    The UI uses this endpoint for local presentation only. All figures are clearly
    synthetic and should not be mistaken for production metrics.
    """
    return {
        "mode": "synthetic-demo",
        "synthetic": True,
        "last_updated": datetime.now(tz=UTC).isoformat(),
        "backend_health": {
            "live": "live",
            "ready": "ready",
            "database": "synthetic",
        },
        "recovery_candidates": [
            {"customer_id": "CUST-1001", "cart_id": "CART-101", "channel": "email", "score": 94},
            {"customer_id": "CUST-1007", "cart_id": "CART-205", "channel": "sms", "score": 88},
            {"customer_id": "CUST-1018", "cart_id": "CART-312", "channel": "email", "score": 81},
        ],
        "message_events": [
            {"event_id": "MSG-0101", "customer_id": "CUST-1001", "event_type": "sent", "status": "accepted"},
            {"event_id": "MSG-0102", "customer_id": "CUST-1007", "event_type": "opened", "status": "observed"},
            {"event_id": "MSG-0103", "customer_id": "CUST-1018", "event_type": "clicked", "status": "observed"},
        ],
        "orders": [
            {"order_id": "ORD-8801", "customer_id": "CUST-1001", "amount": 128.40, "channel": "email"},
            {"order_id": "ORD-8807", "customer_id": "CUST-1007", "amount": 245.10, "channel": "sms"},
        ],
        "attribution": {
            "credited_orders": 2,
            "uncredited_orders": 0,
            "attribution_window_days": 7,
        },
    }
