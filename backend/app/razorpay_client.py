"""
Section 21/27: minimum required Razorpay capabilities, using the official
`razorpay` Python SDK. Never invents endpoints — everything here maps 1:1
to documented SDK methods (client.order.create, client.payment.fetch,
etc.). If credentials aren't configured, every method raises
RazorpayNotConfiguredError so callers can fall back to Simulation Mode
cleanly instead of crashing (section 44).
"""
from .config import settings

try:
    import razorpay
except ImportError:  # pragma: no cover - SDK is in backend/requirements.txt
    razorpay = None


class RazorpayNotConfiguredError(Exception):
    pass


def _get_client():
    if razorpay is None:
        raise RazorpayNotConfiguredError("razorpay SDK not installed")
    if not settings.razorpay_configured:
        raise RazorpayNotConfiguredError(
            "RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET not set — Razorpay Test Mode is inactive"
        )
    return razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))


def create_test_order(amount_paise: int, currency: str = "INR", receipt: str = None) -> dict:
    """amount_paise: integer, smallest currency unit (e.g. 99900 for ₹999)."""
    client = _get_client()
    return client.order.create({
        "amount": amount_paise,
        "currency": currency,
        "receipt": receipt,
        "payment_capture": 1,
    })


def fetch_order(order_id: str) -> dict:
    return _get_client().order.fetch(order_id)


def fetch_payment(payment_id: str) -> dict:
    """API verification fallback (section 27/53) — used when webhook
    information is delayed or contradictory."""
    return _get_client().payment.fetch(payment_id)


def fetch_payments_for_order(order_id: str) -> dict:
    return _get_client().order.payments(order_id)
