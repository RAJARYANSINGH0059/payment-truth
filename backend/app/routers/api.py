from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from ..db import get_db
from ..config import settings
from ..historical_similarity import find_similar_incidents
from ..decision_engine import decide
from ..models.db import Payment, Incident, AuditLog, ModelVersion, IncidentMemory, DataSource
from ..ml_inference import predict_payment_state, model_status
from ..razorpay_client import create_test_order, fetch_payment, RazorpayNotConfiguredError

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
    return {
        "payment_id": p.payment_id, "amount": p.amount, "payment_method": p.payment_method,
        "bank": p.bank, "observed_status": p.observed_status, "source": p.source,
        "true_final_state": p.true_final_state,
        "timeline": [{"timestamp": a.timestamp.isoformat(), "prediction": a.prediction_json,
                       "recommendation": a.recommendation, "confidence": a.confidence} for a in audits],
    }


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


@router.get("/models/metrics")
def models_metrics():
    """Section 65 — reads the metrics.json written by ml/pipeline/train.py
    and incident_detector.py. Never hardcoded."""
    import json
    import os
    out = {}
    for name, fname in [("payment_state_model", "metrics.json"),
                         ("incident_detector", "incident_detector_metrics.json")]:
        path = os.path.join(settings.ML_ARTIFACTS_DIR, fname)
        if os.path.exists(path):
            with open(path) as f:
                out[name] = json.load(f)
        else:
            out[name] = {"status": "not yet trained"}
    out["model_status"] = model_status()
    return out


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


@router.post("/simulation/generate")
def run_simulation(payments: int = 500, seed: int = 42, sim_days: int = 2, db: Session = Depends(get_db)):
    """Section 33 — triggers the synthetic generator, then loads the result
    straight into the live app (scores every payment with the real trained
    model, records real decisions, detects real incidents from the
    generated data). Kept modest by default so it returns within a normal
    request; large runs should use the CLI directly."""
    import subprocess
    import sys as _sys
    import os as _os
    from ..simulation_loader import load_generated_dataset, scan_for_incidents

    repo_root = _os.path.join(_os.path.dirname(__file__), "..", "..", "..")
    result = subprocess.run(
        [_sys.executable, "scripts/generate_dataset.py",
         "--payments", str(payments), "--seed", str(seed), "--sim-days", str(sim_days)],
        cwd=repo_root, capture_output=True, text=True, timeout=120,
    )
    if result.returncode != 0:
        return {"status": "failed", "stdout_tail": result.stdout[-2000:], "stderr_tail": result.stderr[-2000:]}

    data_dir = _os.path.join(repo_root, "data", "demo")
    incident_summary = scan_for_incidents(db, data_dir)  # must run first — load below reads its results
    load_summary = load_generated_dataset(db, data_dir)

    return {
        "status": "ok", "generation": {"payments_requested": payments, "seed": seed, "sim_days": sim_days},
        "loaded_into_app": load_summary, "incidents_detected": incident_summary,
    }


@router.post("/data/import")
async def import_dataset(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Section 34/57 — CSV/JSON upload with validation. Never claims accuracy
    on unlabeled data (section 57): only runs evaluation if ground_truth_final_state
    is present in the uploaded payments file."""
    import csv
    import io
    import json as _json

    raw = await file.read()
    filename = (file.filename or "").lower()

    try:
        if filename.endswith(".json"):
            records = _json.loads(raw)
            if isinstance(records, dict):
                records = records.get("payments", records.get("data", [records]))
        elif filename.endswith(".csv"):
            records = list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))
        else:
            raise HTTPException(400, "unsupported file type — use .csv or .json")
    except (_json.JSONDecodeError, UnicodeDecodeError) as e:
        raise HTTPException(400, f"could not parse file: {e}")

    required_fields = ["payment_id", "amount", "payment_method"]
    valid_rows, invalid_rows = [], []
    seen_ids = set()

    for i, row in enumerate(records):
        problems = []
        for field in required_fields:
            if not row.get(field):
                problems.append(f"missing {field}")
        pid = row.get("payment_id")
        if pid and pid in seen_ids:
            problems.append("duplicate payment_id within upload")
        if pid:
            seen_ids.add(pid)
        if row.get("amount") is not None:
            try:
                float(row["amount"])
            except (ValueError, TypeError):
                problems.append("amount is not numeric")
        if row.get("created_at"):
            try:
                datetime.fromisoformat(str(row["created_at"]).replace("Z", "+00:00"))
            except ValueError:
                problems.append("created_at is not a valid ISO timestamp")

        if problems:
            invalid_rows.append({"row": i, "problems": problems})
        else:
            valid_rows.append(row)

    has_ground_truth = valid_rows and "ground_truth_final_state" in valid_rows[0]

    imported = 0
    for row in valid_rows:
        pid = row["payment_id"]
        existing = db.get(Payment, pid)
        if existing:
            continue
        db.add(Payment(
            payment_id=pid, order_id=row.get("order_id"),
            customer_id=row.get("customer_id"), merchant_id=row.get("merchant_id"),
            amount=float(row["amount"]), payment_method=row["payment_method"],
            bank=row.get("bank"), source="USER_UPLOAD",
            observed_status=row.get("observed_status", "UNKNOWN"),
            true_final_state=row.get("ground_truth_final_state"),
        ))

        # Score with the real trained model — uploaded rows rarely carry
        # the full snapshot feature set (event_count, timing, etc.), so
        # missing ones fall back to neutral defaults inside
        # predict_payment_state(); this is a real prediction on reduced
        # information, not a fabricated one.
        features = {
            "payment_method": row["payment_method"], "bank": row.get("bank") or "UNKNOWN",
            "merchant_type": "unknown", "observed_status_at_snapshot": row.get("observed_status", "UNKNOWN"),
            "amount": float(row["amount"]), "hour_of_day": 0, "day_of_week": 0,
            "previous_payment_count": 0, "previous_success_rate": 0.9,
            "event_count": 1, "duplicate_event_count": 0,
            "time_since_payment_sec": 0, "time_since_last_event_sec": 0,
            "event_order_anomaly": False,
        }
        prediction = predict_payment_state(features)
        confidence = prediction.get("confidence") or 0.0
        recommendation = decide(
            p_success=prediction.get("success") or 0.0, p_pending=prediction.get("pending") or 0.0,
            p_failed=prediction.get("failed") or 0.0, incident_active=False, incident_severity=0.0,
            txn_value=float(row["amount"]), duplicate_risk=False, confidence=confidence,
        )
        db.add(AuditLog(
            entity_type="payment", entity_id=pid, prediction_json=prediction, confidence=confidence,
            evidence_json=features, recommendation=recommendation,
            actual_outcome=row.get("ground_truth_final_state"), model_version=prediction.get("model_version"),
        ))
        imported += 1
    db.add(DataSource(name="USER_UPLOAD", rows_imported=imported, rows_invalid=len(invalid_rows)))
    db.commit()

    evaluation = None
    if has_ground_truth:
        correct = sum(1 for r in valid_rows if r.get("observed_status") == r.get("ground_truth_final_state"))
        evaluation = {
            "note": "naive observed-status-as-prediction accuracy — not the trained model's accuracy",
            "accuracy": round(correct / len(valid_rows), 4) if valid_rows else None,
        }

    return {
        "rows_total": len(records),
        "payments_recognized": len(valid_rows),
        "events_recognized": 0,
        "invalid_rows": len(invalid_rows),
        "invalid_details": invalid_rows[:20],
        "imported_new_payments": imported,
        "ground_truth_present": has_ground_truth,
        "evaluation": evaluation,
    }


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
