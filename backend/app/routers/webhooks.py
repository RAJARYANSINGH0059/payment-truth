import json
from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Header, Request, Response
from sqlalchemy.orm import Session
from fastapi import Depends

from ..db import get_db, SessionLocal
from ..config import settings
from ..webhook_utils import verify_signature, normalize_webhook_payload
from ..models.db import Payment, PaymentEvent, AuditLog
from ..ml_inference import predict_payment_state
from ..decision_engine import decide  # backend/decision_engine.py (Phase 6)

router = APIRouter()


def _process_event(normalized: dict):
    """Runs after the 2xx response has already been sent (section 23).
    Opens its own DB session — the request-scoped session from Depends()
    is closed by the time a BackgroundTask actually runs."""
    payment_id = normalized["payment_id"]
    if not payment_id:
        return
    db = SessionLocal()

    payment = db.get(Payment, payment_id)
    if payment is None:
        payment = Payment(
            payment_id=payment_id, order_id=normalized.get("order_id"),
            amount=(normalized.get("amount") or 0) / 100.0,
            payment_method=normalized.get("method"), bank=normalized.get("bank"),
            created_at=datetime.utcnow(), source="RAZORPAY_TEST",
            observed_status=normalized["observed_status"],
        )
        db.add(payment)
    else:
        # Never let out-of-order or duplicate delivery downgrade an
        # already-authoritative observed status (section 15/50).
        precedence = {"UNKNOWN": 0, "PENDING": 1, "FAILED": 2, "SUCCESS": 3}
        if precedence.get(normalized["observed_status"], 0) >= precedence.get(payment.observed_status, 0):
            payment.observed_status = normalized["observed_status"]

    features = {
        "payment_method": normalized.get("method") or "UNKNOWN",
        "bank": normalized.get("bank") or "UNKNOWN",
        "merchant_type": "unknown", "observed_status_at_snapshot": normalized["observed_status"],
        "amount": (normalized.get("amount") or 0) / 100.0,
        "hour_of_day": datetime.utcnow().hour, "day_of_week": datetime.utcnow().weekday(),
        "previous_payment_count": 0, "previous_success_rate": 0.9,
        "event_count": 1, "duplicate_event_count": 0,
        "time_since_payment_sec": 0, "time_since_last_event_sec": 0,
        "event_order_anomaly": False,
    }
    prediction = predict_payment_state(features)

    db.add(AuditLog(
        entity_type="payment", entity_id=payment_id,
        prediction_json=prediction, confidence=prediction.get("confidence"),
        evidence_json=normalized, recommendation=None,
        model_version=prediction.get("model_version"),
    ))
    try:
        db.commit()
    finally:
        db.close()


@router.post("/api/webhooks/razorpay")
async def razorpay_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
    x_razorpay_signature: str = Header(default=None),
    x_razorpay_event_id: str = Header(default=None),
    db: Session = Depends(get_db),
):
    raw_body = await request.body()

    if not settings.webhook_configured:
        # Section 43/44: never crash because Razorpay isn't configured —
        # but also never accept an unverifiable webhook.
        return Response(status_code=503, content=json.dumps(
            {"status": "rejected", "reason": "RAZORPAY_WEBHOOK_SECRET not configured"}))

    if not verify_signature(raw_body, x_razorpay_signature or ""):
        return Response(status_code=400, content=json.dumps(
            {"status": "rejected", "reason": "invalid signature"}))

    # Deduplicate using x-razorpay-event-id (section 22/14) before doing
    # anything else — a duplicate delivery must be a fast no-op.
    if x_razorpay_event_id:
        existing = db.query(PaymentEvent).filter(
            PaymentEvent.razorpay_event_id == x_razorpay_event_id).first()
        if existing:
            return {"status": "duplicate_ignored", "event_id": x_razorpay_event_id}

    try:
        payload = json.loads(raw_body)
    except json.JSONDecodeError:
        return Response(status_code=400, content=json.dumps(
            {"status": "rejected", "reason": "malformed body"}))

    normalized = normalize_webhook_payload(payload, x_razorpay_event_id or "")

    db.add(PaymentEvent(
        event_id=f"{x_razorpay_event_id or 'noid'}-{normalized['event_type']}",
        payment_id=normalized["payment_id"], event_type=normalized["event_type"],
        received_time=datetime.utcnow(), razorpay_event_id=x_razorpay_event_id,
        raw_payload=payload, source="RAZORPAY_TEST",
    ))
    db.commit()

    # Return 2xx immediately (section 23); heavy work happens after response.
    background_tasks.add_task(_process_event, normalized)
    return {"status": "accepted", "event_type": normalized["event_type"]}
