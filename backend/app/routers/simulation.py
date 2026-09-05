"""Synthetic data generation (loads straight into the live app) and CSV/JSON dataset import."""

from datetime import datetime

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session

from ..db import get_db
from ..decision_engine import decide
from ..ml_inference import predict_payment_state, reload_model
from ..models.db import Payment, AuditLog, DataSource

router = APIRouter(prefix="/api")

@router.post("/simulation/generate")
def run_simulation(background_tasks: BackgroundTasks, payments: int = 500, seed: int = 42,
                    sim_days: int = 2, retrain: bool = True, db: Session = Depends(get_db)):
    """Section 33 — triggers the synthetic generator, then loads the result
    straight into the live app (scores every payment with the real trained
    model, records real decisions, detects real incidents from the
    generated data). Kept modest by default so it returns within a normal
    request; large runs should use the CLI directly.

    retrain=True (default) also retrains the model on the freshly
    generated data.demo dataset in the background, then hot-swaps the
    running model via ml_inference.reload_model() — no manual
    `python ml/pipeline/train.py` needed after each generation. Retraining
    runs in the background so this endpoint still returns quickly; check
    /api/models/metrics afterward (a few seconds later) to see the
    updated numbers."""
    if payments < 1:
        # Without this check, `payments=0` would exit the generator
        # cleanly but leave whatever CSVs already exist in data/demo/
        # untouched — then this endpoint would load THAT stale leftover
        # data and report success, misleadingly implying it matched the
        # request. Found via testing this exact edge case. Reject clearly
        # instead of silently doing something the caller didn't ask for.
        raise HTTPException(400, "payments must be at least 1")
    if sim_days < 1:
        raise HTTPException(400, "sim_days must be at least 1")

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

    if retrain:
        background_tasks.add_task(_retrain_in_background, repo_root, data_dir)

    return {
        "status": "ok", "generation": {"payments_requested": payments, "seed": seed, "sim_days": sim_days},
        "loaded_into_app": load_summary, "incidents_detected": incident_summary,
        "retraining": "started in background — check /api/models/metrics shortly" if retrain else "skipped",
    }


def _retrain_in_background(repo_root: str, data_dir: str):
    """Retrains XGBoost + the incident detector on the freshly generated
    dataset, writes new artifacts to ml/artifacts, then hot-swaps the
    running model. Runs as a FastAPI background task — after the HTTP
    response for /simulation/generate has already been sent, same pattern
    as webhook processing (section 23)."""
    import subprocess
    import sys as _sys
    import os as _os

    artifacts_dir = _os.path.join(repo_root, "ml", "artifacts")
    for script in ("ml/pipeline/train.py", "ml/pipeline/incident_detector.py"):
        subprocess.run(
            [_sys.executable, script, "--data", data_dir, "--out", artifacts_dir],
            cwd=repo_root, capture_output=True, text=True, timeout=300,
        )
    reload_model()

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

    # Rows can be heterogeneous in JSON uploads (unlike CSV's uniform
    # header), so ground truth presence must be checked across ALL rows,
    # not just the first — found via testing a JSON upload where the
    # first row lacked the field but a later row had it.
    has_ground_truth = any(r.get("ground_truth_final_state") for r in valid_rows)

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
        # Only score rows that actually HAVE ground truth — without this,
        # a row missing both observed_status and ground_truth_final_state
        # would compare None == None as a false "correct" match, silently
        # inflating accuracy. Found via the same heterogeneous-JSON test
        # that caught the has_ground_truth bug above.
        scoreable = [r for r in valid_rows if r.get("ground_truth_final_state")]
        correct = sum(1 for r in scoreable if r.get("observed_status") == r.get("ground_truth_final_state"))
        evaluation = {
            "note": "naive observed-status-as-prediction accuracy — not the trained model's accuracy",
            "scored_rows": len(scoreable),
            "accuracy": round(correct / len(scoreable), 4) if scoreable else None,
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
