"""Overview aggregates and the searchable audit trail."""

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.db import Payment, Incident, AuditLog

router = APIRouter(prefix="/api")

@router.get("/overview")
def overview(db: Session = Depends(get_db)):
    """Section 30/62 — Overview page aggregates. All values are computed
    live from the DB; nothing here is hardcoded, and each financial figure
    carries its own basis (VERIFIED/ESTIMATED/PREDICTED/SIMULATED)."""
    total = db.query(Payment).count()
    uncertain = db.query(Payment).filter(
        Payment.observed_status.in_(["PENDING", "UNKNOWN"])).count()
    success = db.query(Payment).filter(Payment.observed_status == "SUCCESS").count()
    payment_health = round(100 * success / total, 1) if total else None

    incidents = db.query(Incident).all()
    active_incidents = [i for i in incidents if i.resolved_at is None]
    revenue_at_risk = sum(i.revenue_exposure or 0 for i in active_incidents)
    revenue_protected = sum(
        (i.revenue_exposure or 0) for i in incidents
        if i.resolved_at is not None and i.financial_basis == "VERIFIED"
    )

    return {
        "payment_health_pct": payment_health,
        "total_payments": total,
        "uncertain_payments": uncertain,
        "revenue_at_risk": {"value": round(revenue_at_risk, 2), "basis": "ESTIMATED"},
        "revenue_protected": {"value": round(revenue_protected, 2), "basis": "VERIFIED"},
        "active_incidents": len(active_incidents),
    }

@router.get("/audit")
def list_audit(limit: int = 100, db: Session = Depends(get_db)):
    """Section 35/66 — searchable decision/prediction trail."""
    from ..models.db import AuditLog
    rows = db.query(AuditLog).order_by(AuditLog.timestamp.desc()).limit(limit).all()
    return [{
        "timestamp": r.timestamp.isoformat(), "entity_type": r.entity_type, "entity_id": r.entity_id,
        "prediction": r.prediction_json, "confidence": r.confidence, "recommendation": r.recommendation,
        "model_version": r.model_version,
    } for r in rows]
