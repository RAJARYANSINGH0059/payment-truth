"""Prediction vs Reality aggregate, LLM explanation, and the three formal experiment result readers."""

import os

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.db import Payment, AuditLog
from ..prediction_evaluation import evaluate as evaluate_prediction, aggregate as aggregate_verdicts

router = APIRouter(prefix="/api")

@router.get("/experiments/prediction-vs-reality")
def prediction_vs_reality(db: Session = Depends(get_db)):
    """Completion-prompt item 2: aggregate accuracy + confusion matrix over
    every prediction that has since obtained ground truth. Computed live
    from AuditLog + Payment on every call — never cached/precomputed, so
    it always reflects the current DB state."""
    rows = (
        db.query(AuditLog, Payment)
        .join(Payment, AuditLog.entity_id == Payment.payment_id)
        .filter(AuditLog.entity_type == "payment")
        .all()
    )
    verdicts = []
    for audit, payment in rows:
        actual = audit.actual_outcome or payment.true_final_state
        v = evaluate_prediction(audit.prediction_json, actual)
        if v is not None:
            verdicts.append(v)

    summary = aggregate_verdicts(verdicts)
    # A few concrete examples for the UI — one correct, one incorrect —
    # so the page can show real cases, not just the aggregate numbers.
    examples_correct = [v for v in verdicts if v.was_correct][:1]
    examples_incorrect = [v for v in verdicts if not v.was_correct][:1]
    summary["sample_correct"] = [
        {"predicted_class": v.predicted_class, "actual_class": v.actual_class,
         "probability_of_actual_class": v.probability_of_actual_class} for v in examples_correct
    ]
    summary["sample_incorrect"] = [
        {"predicted_class": v.predicted_class, "actual_class": v.actual_class,
         "probability_of_actual_class": v.probability_of_actual_class} for v in examples_incorrect
    ]
    return summary

@router.post("/explain")
def explain_endpoint(payload: dict):
    """Section 19-24: LLM (or deterministic fallback) explanation layer.
    payload must contain prediction/probabilities/evidence/recommendation
    — this endpoint only narrates those, never computes or changes them."""
    from ..llm_explain import explain
    result = explain(payload)
    return {"explanation": result.text, "source": result.source}

@router.get("/experiments/unseen-incident")
def experiment_unseen_incident():
    import json as _json
    path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "experiments", "unseen_incident", "metrics.json")
    if not os.path.exists(path):
        return {"status": "not yet run", "how_to_run": "python experiments/unseen_incident/run.py"}
    with open(path) as f:
        return _json.load(f)

@router.get("/experiments/memory")
def experiment_memory():
    import json as _json
    path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "experiments", "incident_memory", "metrics.json")
    if not os.path.exists(path):
        return {"status": "not yet run", "how_to_run": "python experiments/incident_memory/run.py"}
    with open(path) as f:
        return _json.load(f)

@router.get("/experiments/revenue")
def experiment_revenue():
    import json as _json
    path = os.path.join(os.path.dirname(__file__), "..", "..", "..", "experiments", "revenue_protection", "metrics.json")
    if not os.path.exists(path):
        return {"status": "not yet run", "how_to_run": "python experiments/revenue_protection/run.py"}
    with open(path) as f:
        return _json.load(f)
