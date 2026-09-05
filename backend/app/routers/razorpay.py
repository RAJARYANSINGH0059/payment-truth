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
        # Key ID (not the secret) is safe to expose to the frontend — Razorpay's
        # own Checkout.js requires it client-side to open the payment modal.
        # Never expose RAZORPAY_KEY_SECRET or RAZORPAY_WEBHOOK_SECRET here.
        "key_id": settings.RAZORPAY_KEY_ID if settings.razorpay_configured else None,
    }

@router.post("/razorpay/test-order")
def create_demo_order():
    """₹999 demo product order (section 25) — fails cleanly if Razorpay
    Test Mode isn't configured, so the endpoint never pretends to succeed.
    Also catches any other failure talking to Razorpay's servers (network
    error, timeout, malformed response, Razorpay-side error) — found via
    live testing that an uncaught exception here leaked a full Python
    traceback to the client instead of a clean error (see
    docs/FAILURE_RECOVERY.md)."""
    try:
        order = create_test_order(amount_paise=99900, receipt="payment-truth-demo")
        return {"status": "created", "order": order}
    except RazorpayNotConfiguredError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        # Deliberately broad: this is the boundary to an external, unreliable
        # network service — the specific failure (SSL error, timeout, 4xx/5xx
        # from Razorpay) isn't something the caller can act on differently,
        # and the raw exception may contain internal details that shouldn't
        # reach the client. Log the real error server-side for debugging.
        import logging
        logging.getLogger(__name__).error(f"Razorpay order creation failed: {e}")
        raise HTTPException(502, "Could not reach Razorpay right now — the request may have been "
                                  "blocked by network restrictions or Razorpay's service may be "
                                  "unavailable. This is not a configuration error.")

@router.get("/razorpay/verify/{payment_id}")
def verify_payment(payment_id: str):
    """API verification fallback (section 27/53). Same broad-catch reasoning
    as create_demo_order above."""
    try:
        return fetch_payment(payment_id)
    except RazorpayNotConfiguredError as e:
        raise HTTPException(503, str(e))
    except Exception as e:
        import logging
        logging.getLogger(__name__).error(f"Razorpay payment verification failed: {e}")
        raise HTTPException(502, "Could not reach Razorpay right now to verify this payment.")
