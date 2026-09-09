from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import init_db, engine
from .config import settings
from .ml_inference import model_status
from .routers import webhooks, payments, incidents, dashboard, models_metrics, simulation, experiments, razorpay


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Payment Truth", description="Know the payment truth before you act.",
              lifespan=lifespan)

app.add_middleware(
    # allow_origins=["*"] deliberately does NOT pair with
    # allow_credentials=True — browsers reject that combination per the
    # CORS spec (a wildcard origin can't be echoed back for a credentialed
    # request), so allow_credentials=True here was silently doing nothing
    # useful. This app has no cookie-based auth, so it isn't needed.
    # Found via a deliberate audit of every middleware/dependency claim
    # against what it actually does (see docs/FAILURE_RECOVERY.md).
    CORSMiddleware, allow_origins=["*"],
    allow_methods=["*"], allow_headers=["*"],
)

# Grouped by responsibility (see backend/app/routers/ARCHITECTURE.md):
# webhooks (Razorpay inbound), payments/incidents (core entities),
# dashboard (aggregates), models_metrics (ML reporting), simulation
# (data generation/import), experiments (formal evaluation + LLM
# explanation), razorpay (outbound Test Mode API calls).
app.include_router(webhooks.router)
app.include_router(payments.router)
app.include_router(incidents.router)
app.include_router(dashboard.router)
app.include_router(models_metrics.router)
app.include_router(simulation.router)
app.include_router(experiments.router)
app.include_router(razorpay.router)


@app.get("/health")
def health():
    """Section 43 — must return status:ok even when Razorpay/ML aren't
    configured; the app must never fail to start because of that."""
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
        "razorpay": "configured" if settings.razorpay_configured else "not_configured",
    }
