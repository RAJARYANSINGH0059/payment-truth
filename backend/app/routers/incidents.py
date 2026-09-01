"""Incident listing + detail, including historical-similarity matches."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..historical_similarity import find_similar_incidents
from ..models.db import Incident, IncidentMemory

router = APIRouter(prefix="/api")

@router.get("/incidents")
def list_incidents(db: Session = Depends(get_db)):
    rows = db.query(Incident).order_by(Incident.detected_at.desc()).all()
    return [{"incident_id": r.incident_id, "severity": r.severity, "root_cause": r.root_cause,
             "root_cause_confidence": r.root_cause_confidence, "revenue_exposure": r.revenue_exposure,
             "expected_recoverable_value": r.expected_recoverable_value,
             "financial_basis": r.financial_basis} for r in rows]

@router.get("/incidents/{incident_id}")
def get_incident(incident_id: str, db: Session = Depends(get_db)):
    r = db.get(Incident, incident_id)
    if not r:
        raise HTTPException(404, "incident not found")

    memory_rows = db.query(IncidentMemory).filter(IncidentMemory.incident_id != incident_id).all()
    current = {
        "payment_method": r.affected_method, "bank": r.affected_bank,
        "root_cause": r.root_cause,
        "failure_rate": (memory_rows and next(
            (m.failure_rate for m in memory_rows if m.incident_id == incident_id), None)) or None,
        "duration_minutes": None,
    }
    historical = [{
        "incident_id": m.incident_id, "payment_method": m.payment_method, "bank": m.bank,
        "root_cause": m.root_cause, "failure_rate": m.failure_rate,
        "duration_minutes": m.duration_minutes, "recommended_action": m.recommended_action,
        "actual_outcome": m.actual_outcome, "revenue_impact": m.revenue_impact,
    } for m in memory_rows]
    similar = find_similar_incidents(current, historical) if historical else []

    return {
        "incident_id": r.incident_id, "severity": r.severity, "affected_bank": r.affected_bank,
        "affected_method": r.affected_method, "root_cause": r.root_cause,
        "root_cause_confidence": r.root_cause_confidence,
        "supporting_evidence": r.supporting_evidence_json, "contradicting_evidence": r.contradicting_evidence_json,
        "revenue_exposure": r.revenue_exposure, "expected_recoverable_value": r.expected_recoverable_value,
        "financial_basis": r.financial_basis, "outcome": r.outcome,
        "similar_incidents": [
            {"incident_id": s.incident_id, "similarity_pct": s.similarity_pct, "matched_on": s.matched_on,
             "recommended_action": s.recommended_action, "actual_outcome": s.actual_outcome,
             "revenue_impact": s.revenue_impact}
            for s in similar
        ],
    }
