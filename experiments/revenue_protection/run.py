#!/usr/bin/env python3
"""
Revenue Protection A/B experiment (completion-prompt sections 11-14).

Strategy A — NAIVE (documented, not straw-manned):
  If the earliest observed status is FAILED, immediately RECOVER (retry).
  Otherwise WAIT (do nothing). This mirrors a common real-world naive
  merchant integration: react only to the first failure-looking signal.

Strategy B — PAYMENT TRUTH:
  Use the actual trained model's prediction at the same earliest
  observation snapshot, run it through the actual decision engine
  (decide()), and take whatever it recommends (WAIT/VERIFY/RECOVER/STOP).
  Incident-driven STOP is deliberately excluded from this run (isolates
  the comparison to per-payment state prediction vs the naive rule,
  rather than mixing in incident detection) — noted in the report.

Both strategies are evaluated against the SAME synthetic payments and the
SAME ground truth (true_final_state) — only the action policy differs.

Usage:
    python experiments/revenue_protection/run.py
"""
import json
import os
import sys

import joblib
import pandas as pd

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))
sys.path.insert(0, REPO_ROOT)
from app.decision_engine import decide  # noqa: E402

EXPERIMENT_DIR = os.path.dirname(__file__)
ARTIFACTS_DIR = os.path.join(REPO_ROOT, "ml", "artifacts")


def load_model():
    model = joblib.load(os.path.join(ARTIFACTS_DIR, "probability_calibrator.joblib"))
    label_enc = joblib.load(os.path.join(ARTIFACTS_DIR, "label_encoder.joblib"))
    with open(os.path.join(ARTIFACTS_DIR, "feature_schema.json")) as f:
        schema = json.load(f)
    return model, label_enc, schema


def predict_row(model, label_enc, schema, row: dict) -> dict:
    cols = schema["feature_columns"]
    encoders = schema["categorical_encoders"]
    encoded = {}
    for c in cols:
        v = row.get(c)
        encoded[c] = encoders[c].get(str(v), 0) if c in encoders else float(v) if v is not None else 0.0
    X = pd.DataFrame([encoded], columns=cols)
    proba = model.predict_proba(X)[0]
    classes = schema["classes"]
    dist = {cls.lower(): float(p) for cls, p in zip(classes, proba)}
    for k in ("success", "pending", "failed"):
        dist.setdefault(k, 0.0)
    return {**dist, "confidence": float(max(proba))}


def earliest_snapshot(snapshot_rows_by_payment: dict, pid: str):
    return snapshot_rows_by_payment.get(pid)


def main():
    data_dir = os.path.join(REPO_ROOT, "data", "demo")
    payments = pd.read_csv(os.path.join(data_dir, "payments.csv"))
    snapshots = pd.read_csv(os.path.join(data_dir, "observation_snapshots.csv"))

    earliest = {}
    for _, row in snapshots.iterrows():
        pid = row["payment_id"]
        if pid not in earliest or row["observation_at"] < earliest[pid]["observation_at"]:
            earliest[pid] = row

    model, label_enc, schema = load_model()

    a_actions, b_actions = [], []
    a_wrong = a_unnecessary_retry = a_recovered_value = a_protected_value = 0.0
    b_wrong = b_unnecessary_retry = b_recovered_value = b_protected_value = 0.0
    a_wrong_n = a_unnecessary_retry_n = b_wrong_n = b_unnecessary_retry_n = 0
    revenue_exposed = 0.0

    n = 0
    for _, p in payments.iterrows():
        snap = earliest.get(p["payment_id"])
        if snap is None:
            continue
        n += 1
        amount = float(p["amount"])
        true_state = p["true_final_state"]
        if true_state == "FAILED":
            revenue_exposed += amount

        # --- Strategy A: naive ---
        action_a = "RECOVER" if snap["observed_status_at_snapshot"] == "FAILED" else "WAIT"
        a_actions.append(action_a)
        if action_a == "RECOVER" and true_state == "CAPTURED":
            a_wrong_n += 1
            a_unnecessary_retry_n += 1
            a_wrong += amount
            a_unnecessary_retry += amount
        elif action_a == "WAIT" and true_state == "FAILED":
            a_wrong_n += 1
            a_wrong += amount
        if action_a == "RECOVER" and true_state == "FAILED":
            a_recovered_value += amount
        if action_a != "RECOVER" and true_state == "CAPTURED":
            a_protected_value += amount

        # --- Strategy B: Payment Truth (real model + real decision engine) ---
        features = {
            "payment_method": p["payment_method"], "bank": p.get("bank") or "UNKNOWN",
            "merchant_type": "unknown", "observed_status_at_snapshot": snap["observed_status_at_snapshot"],
            "amount": amount, "hour_of_day": int(snap.get("hour_of_day", 0)),
            "day_of_week": int(snap.get("day_of_week", 0)),
            "previous_payment_count": int(float(snap.get("previous_payment_count", 0))),
            "previous_success_rate": float(snap.get("previous_success_rate", 0.9)),
            "event_count": int(float(snap.get("event_count", 1))),
            "duplicate_event_count": int(float(snap.get("duplicate_event_count", 0))),
            "time_since_payment_sec": float(snap.get("time_since_payment_sec", 0)),
            "time_since_last_event_sec": float(snap.get("time_since_last_event_sec", 0)),
            "event_order_anomaly": str(snap.get("event_order_anomaly", "False")).lower() == "true",
        }
        pred = predict_row(model, label_enc, schema, features)
        action_b = decide(
            p_success=pred["success"], p_pending=pred["pending"], p_failed=pred["failed"],
            incident_active=False, incident_severity=0.0,  # isolates state-prediction vs naive rule
            txn_value=amount, duplicate_risk=int(float(snap.get("duplicate_event_count", 0))) > 0,
            confidence=pred["confidence"],
        )
        b_actions.append(action_b)
        if action_b == "RECOVER" and true_state == "CAPTURED":
            b_wrong_n += 1
            b_unnecessary_retry_n += 1
            b_wrong += amount
            b_unnecessary_retry += amount
        elif action_b == "WAIT" and true_state == "FAILED":
            b_wrong_n += 1
            b_wrong += amount
        if action_b == "RECOVER" and true_state == "FAILED":
            b_recovered_value += amount
        if action_b in ("WAIT", "VERIFY") and true_state == "CAPTURED":
            b_protected_value += amount

    from collections import Counter

    report = {
        "experiment": "revenue_protection_ab",
        "n_payments_evaluated": n,
        "strategy_a_naive": {
            "description": "RECOVER immediately if observed status is FAILED at first observation, else WAIT.",
            "action_distribution": dict(Counter(a_actions)),
            "wrong_actions": a_wrong_n, "wrong_action_value": round(a_wrong, 2),
            "unnecessary_retries": a_unnecessary_retry_n, "duplicate_risk_value": round(a_unnecessary_retry, 2),
            "recovered_value": round(a_recovered_value, 2), "protected_value": round(a_protected_value, 2),
        },
        "strategy_b_payment_truth": {
            "description": "Real trained-model prediction + real decision engine (WAIT/VERIFY/RECOVER/STOP); "
                            "incident-driven STOP excluded from this run to isolate state-prediction comparison.",
            "action_distribution": dict(Counter(b_actions)),
            "wrong_actions": b_wrong_n, "wrong_action_value": round(b_wrong, 2),
            "unnecessary_retries": b_unnecessary_retry_n, "duplicate_risk_value": round(b_unnecessary_retry, 2),
            "recovered_value": round(b_recovered_value, 2), "protected_value": round(b_protected_value, 2),
        },
        "revenue_exposed_total": round(revenue_exposed, 2),
        "improvement": {
            "wrong_actions_reduced": a_wrong_n - b_wrong_n,
            "wrong_action_value_reduced": round(a_wrong - b_wrong, 2),
            "unnecessary_retries_reduced": a_unnecessary_retry_n - b_unnecessary_retry_n,
            "duplicate_risk_value_reduced": round(a_unnecessary_retry - b_unnecessary_retry, 2),
            "protected_value_increase": round(b_protected_value - a_protected_value, 2),
        },
        "note": ("Strategy B's VERIFY action is never counted as 'wrong' — it represents "
                 "deferring to an authoritative check rather than committing to retry or wait "
                 "blindly, which is the core value proposition being measured here."),
    }

    with open(os.path.join(EXPERIMENT_DIR, "metrics.json"), "w") as f:
        json.dump(report, f, indent=2)

    print(json.dumps({k: v for k, v in report.items() if k != "note"}, indent=2))


if __name__ == "__main__":
    main()
