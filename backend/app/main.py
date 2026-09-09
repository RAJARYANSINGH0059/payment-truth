from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import init_db, engine
from .config import settings
from .ml_inference import model_status

from .routers import (
    webhooks,
    payments,
    incidents,
    dashboard,
    models_metrics,
    simulation,
    experiments,
    razorpay,
    recovery,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(
    title="Payment Truth",
    description="Know the payment truth before you act.",
    lifespan=lifespan,
)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --------------------------------------------------
# ROUTERS
# --------------------------------------------------

# Webhooks — Razorpay inbound events
app.include_router(webhooks.router)

# Core payment and incident entities
app.include_router(payments.router)
app.include_router(incidents.router)

# Dashboard / overview
app.include_router(dashboard.router)

# ML model reporting
app.include_router(models_metrics.router)

# Simulation / data generation
app.include_router(simulation.router)

# Experiments / evaluation / explanations
app.include_router(experiments.router)

# Razorpay outbound Test Mode API calls
app.include_router(razorpay.router)

# Recovery workflow
app.include_router(recovery.router)


# --------------------------------------------------
# HEALTH CHECK
# --------------------------------------------------

@app.get("/health")
def health():
    """
    Health endpoint.

    The API must return status:ok even when Razorpay
    or ML components are not configured.

    The application must never fail to start simply
    because an optional external service is unavailable.
    """

    db_ok = True

    try:
        with engine.connect():
            pass
    except Exception:
        db_ok = False

    return {
        "status": "ok",
        "database": "ok" if db_ok else "unavailable",
        "ml_model": model_status(),
        "simulation": "available",
        "razorpay": (
            "configured"
            if settings.razorpay_configured
            else "not_configured"
        ),
    }
