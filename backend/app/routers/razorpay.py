"""Razorpay Test Mode status, demo order creation, and API-verification fallback."""

from fastapi import APIRouter, HTTPException

from ..config import settings
from ..razorpay_client import create_test_order, fetch_payment, RazorpayNotConfiguredError

router = APIRouter(prefix="/api")

@router.get("/razorpay/status")
def razorpay_status():
    return {
        "environment": settings.RAZORPAY_ENV,
        "api": "connected" if settings.razorpay_configured else "not_connected",
        "webhook": "connected" if settings.webhook_configured else "not_connected",
    }

@router.post("/razorpay/test-order")
def create_demo_order():
    """₹999 demo product order (section 25) — fails cleanly if Razorpay
    Test Mode isn't configured, so the endpoint never pretends to succeed."""
    try:
        order = create_test_order(amount_paise=99900, receipt="payment-truth-demo")
        return {"status": "created", "order": order}
    except RazorpayNotConfiguredError as e:
        raise HTTPException(503, str(e))

@router.get("/razorpay/verify/{payment_id}")
def verify_payment(payment_id: str):
    """API verification fallback (section 27/53)."""
    try:
        return fetch_payment(payment_id)
    except RazorpayNotConfiguredError as e:
        raise HTTPException(503, str(e))
