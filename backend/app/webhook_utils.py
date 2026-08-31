"""
Section 22/52: raw-body HMAC-SHA256 signature validation for Razorpay
webhooks, plus normalization of provider payloads into our internal
schema (section 50). This module never talks to the network — API calls
(order creation, payment fetch) live in razorpay_client.py.
"""
import hmac
import hashlib
from datetime import datetime, timezone

from .config import settings


def verify_signature(raw_body: bytes, signature_header: str) -> bool:
    """Returns False (never raises) on missing secret/signature — callers
    must treat False as 'reject the webhook', not 'skip validation'."""
    if not settings.RAZORPAY_WEBHOOK_SECRET or not signature_header:
        return False
    expected = hmac.new(
        settings.RAZORPAY_WEBHOOK_SECRET.encode("utf-8"),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature_header)


EVENT_TYPE_TO_OBSERVED = {
    "payment.authorized": "PENDING",
    "payment.captured": "SUCCESS",
    "payment.failed": "FAILED",
    "order.paid": "SUCCESS",
}


def normalize_webhook_payload(payload: dict, razorpay_event_id: str) -> dict:
    """Convert a raw Razorpay webhook body into our internal event schema
    (section 50). Never train a model directly on raw Razorpay JSON — this
    normalized shape is the only thing that should reach the DB/ML layer."""
    event_type = payload.get("event", "unknown")
    entity = (
        payload.get("payload", {}).get("payment", {}).get("entity", {})
        or payload.get("payload", {}).get("order", {}).get("entity", {})
    )
    return {
        "source": "RAZORPAY_TEST",
        "razorpay_event_id": razorpay_event_id,
        "payment_id": entity.get("id") or entity.get("order_id"),
        "order_id": entity.get("order_id"),
        "event_type": event_type,
        "event_received_at": datetime.now(timezone.utc).isoformat(),
        "observed_status": EVENT_TYPE_TO_OBSERVED.get(event_type, "UNKNOWN"),
        "amount": entity.get("amount"),
        "method": entity.get("method"),
        "bank": entity.get("bank"),
    }
