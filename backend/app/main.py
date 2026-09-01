from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .db import init_db, engine
from .config import settings
from .ml_inference import model_status
from .routers import webhooks, payments, incidents, dashboard, models_metrics, simulation, experiments, razorpay

app = FastAPI(title="Payment Truth", description="Know the payment truth before you act.")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True,
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


@app.on_event("startup")
def on_startup():
    init_db()


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
