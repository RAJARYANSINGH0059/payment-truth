"""Payment listing + detail, including the Prediction vs Reality verdict per prediction."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.db import Payment, AuditLog
from ..prediction_evaluation import evaluate as evaluate_prediction

router = APIRouter(prefix="/api")

@router.get("/payments")
def list_payments(limit: int = 50, db: Session = Depends(get_db)):
    rows = db.query(Payment).order_by(Payment.created_at.desc()).limit(limit).all()
    return [{"payment_id": r.payment_id, "amount": r.amount, "payment_method": r.payment_method,
             "bank": r.bank, "observed_status": r.observed_status, "source": r.source,
             "created_at": r.created_at.isoformat() if r.created_at else None} for r in rows]

@router.get("/payments/{payment_id}")
def get_payment(payment_id: str, db: Session = Depends(get_db)):
    p = db.get(Payment, payment_id)
    if not p:
        raise HTTPException(404, "payment not found")
    audits = db.query(AuditLog).filter(AuditLog.entity_id == payment_id).order_by(AuditLog.timestamp).all()

    timeline = []
    for a in audits:
        actual = a.actual_outcome or p.true_final_state
        verdict = evaluate_prediction(a.prediction_json, actual)
        timeline.append({
            "timestamp": a.timestamp.isoformat(), "prediction": a.prediction_json,
            "recommendation": a.recommendation, "confidence": a.confidence,
            "verdict": None if verdict is None else {
                "predicted_class": verdict.predicted_class, "actual_class": verdict.actual_class,
                "probability_of_actual_class": verdict.probability_of_actual_class,
                "was_correct": verdict.was_correct,
            },
        })

    return {
        "payment_id": p.payment_id, "amount": p.amount, "payment_method": p.payment_method,
        "bank": p.bank, "observed_status": p.observed_status, "source": p.source,
        "true_final_state": p.true_final_state,
        "timeline": timeline,
    }
