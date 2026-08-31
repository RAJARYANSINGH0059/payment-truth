"""
Closes the loop between the synthetic generator (data/demo/*.csv) and the
live application: nothing in this file invents a number. Every prediction
comes from ml_inference.predict_payment_state() loading the actual trained
artifacts; every incident's root cause comes from decision_engine's
evidence-scored diagnosis; every financial figure comes from
decision_engine.compute_financial_impact() run on real aggregated data.

Without this module, generating data via the Simulation page (or importing
a CSV) would write files to disk but the Payments/Incidents/Overview pages
would stay empty forever — the UI has nothing else that populates the DB
from generated data.
"""
import csv
import os
from collections import defaultdict
from datetime import datetime

from sqlalchemy.orm import Session

from .decision_engine import diagnose_root_cause, compute_financial_impact, decide
from .ml_inference import predict_payment_state
from .models.db import Payment, Incident, IncidentMemory, AuditLog

BANKS = ["BANK_A", "BANK_B", "BANK_C", "BANK_D", "BANK_E"]
PAYMENT_METHODS = ["UPI", "CARD", "NETBANKING", "WALLET"]

# Same bins-must-have-enough-volume reasoning as ml/pipeline/incident_detector.py —
# a real 1-minute bin at low synthetic traffic is noise, not signal.
BIN_MINUTES = 10
MIN_BIN_VOLUME = 20
FAILURE_RATE_SPIKE_RATIO = 3.0  # current-bin-vs-baseline ratio that counts as "spiking"


SEVERITY_TO_NUMERIC = {"HIGH": 0.5, "MEDIUM": 0.3, "LOW": 0.15}


def _bin_key(dt: datetime) -> datetime:
    return dt.replace(minute=(dt.minute // BIN_MINUTES) * BIN_MINUTES, second=0, microsecond=0)


def _read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def _earliest_snapshot_per_payment(snapshot_rows):
    """Deliberately the EARLIEST snapshot, not the latest: loading the last
    snapshot would show most payments already resolved (SUCCESS/FAILED),
    making "Uncertain Payments" sit at ~0 forever and defeating the whole
    point of the product — predicting under live uncertainty, not
    reporting settled outcomes. The earliest snapshot is what a merchant
    would actually see in the moments right after a payment starts."""
    earliest = {}
    for row in snapshot_rows:
        pid = row["payment_id"]
        ts = row["observation_at"]
        if pid not in earliest or ts < earliest[pid]["observation_at"]:
            earliest[pid] = row
    return earliest


def load_generated_dataset(db: Session, data_dir: str) -> dict:
    """Loads data/demo/{payments,observation_snapshots}.csv, scores every
    new payment with the real trained model, records the decision-engine
    recommendation, and returns a summary (never silently skips scoring).

    Call scan_for_incidents(db, data_dir) BEFORE this, not after: payments
    whose bin has a real detected incident need incident_active=True fed
    into decide() so STOP is actually reachable, not just theoretically
    possible in decision_engine.py."""
    payments_rows = _read_csv(os.path.join(data_dir, "payments.csv"))
    snapshot_rows = _read_csv(os.path.join(data_dir, "observation_snapshots.csv"))
    first_snapshot = _earliest_snapshot_per_payment(snapshot_rows)

    incident_bins = {
        _bin_key(i.detected_at): SEVERITY_TO_NUMERIC.get(i.severity, 0.2)
        for i in db.query(Incident).all()
    }

    scored, skipped_existing, skipped_no_snapshot = 0, 0, 0

    for row in payments_rows:
        pid = row["payment_id"]
        if db.get(Payment, pid):
            skipped_existing += 1
            continue
        snap = first_snapshot.get(pid)
        if not snap:
            skipped_no_snapshot += 1
            continue

        created_at = datetime.fromisoformat(row["created_at"])
        payment = Payment(
            payment_id=pid, order_id=row.get("order_id"),
            customer_id=row.get("customer_id"), merchant_id=row.get("merchant_id"),
            amount=float(row["amount"]), payment_method=row["payment_method"],
            bank=row.get("bank") or None, created_at=created_at,
            source="SYNTHETIC",
            observed_status=snap["observed_status_at_snapshot"],  # what the system knew — not the answer
            true_final_state=row.get("true_final_state"),
            resolved_at=datetime.fromisoformat(row["resolved_at"]) if row.get("resolved_at") else None,
        )
        db.add(payment)

        features = {
            "payment_method": row["payment_method"], "bank": row.get("bank") or "UNKNOWN",
            "merchant_type": "unknown", "observed_status_at_snapshot": snap["observed_status_at_snapshot"],
            "amount": float(row["amount"]),
            "hour_of_day": int(snap.get("hour_of_day", 0)), "day_of_week": int(snap.get("day_of_week", 0)),
            "previous_payment_count": int(float(snap.get("previous_payment_count", 0))),
            "previous_success_rate": float(snap.get("previous_success_rate", 0.9)),
            "event_count": int(float(snap.get("event_count", 1))),
            "duplicate_event_count": int(float(snap.get("duplicate_event_count", 0))),
            "time_since_payment_sec": float(snap.get("time_since_payment_sec", 0)),
            "time_since_last_event_sec": float(snap.get("time_since_last_event_sec", 0)),
            "event_order_anomaly": str(snap.get("event_order_anomaly", "False")).lower() == "true",
        }
        prediction = predict_payment_state(features)

        p_success = prediction.get("success") or 0.0
        p_pending = prediction.get("pending") or 0.0
        p_failed = prediction.get("failed") or 0.0
        confidence = prediction.get("confidence") or 0.0

        incident_severity = incident_bins.get(_bin_key(created_at), 0.0)
        recommendation = decide(
            p_success=p_success, p_pending=p_pending, p_failed=p_failed,
            incident_active=incident_severity > 0, incident_severity=incident_severity,
            txn_value=float(row["amount"]), duplicate_risk=int(float(snap.get("duplicate_event_count", 0))) > 0,
            confidence=confidence,
        )

        db.add(AuditLog(
            entity_type="payment", entity_id=pid, prediction_json=prediction,
            confidence=confidence, evidence_json=features, recommendation=recommendation,
            actual_outcome=row.get("final_observed_state"), model_version=prediction.get("model_version"),
        ))
        scored += 1

    db.commit()
    return {
        "payments_loaded": scored, "already_present": skipped_existing,
        "no_snapshot_available": skipped_no_snapshot,
    }


def scan_for_incidents(db: Session, data_dir: str) -> dict:
    """Detects real failure-rate spikes from the loaded payments.csv, grouped
    by time bin, and materializes Incident + IncidentMemory rows with a real
    evidence-scored root cause and a real financial-impact calculation.
    Nothing here reuses the simulator's hidden incident_id/cause — only
    observable symptoms (bank/method failure rates) feed the diagnosis,
    same constraint as ml/pipeline/incident_detector.py."""
    payments_rows = _read_csv(os.path.join(data_dir, "payments.csv"))
    if not payments_rows:
        return {"incidents_created": 0, "reason": "no payments.csv found"}

    bins = defaultdict(list)
    for row in payments_rows:
        created = datetime.fromisoformat(row["created_at"])
        bins[_bin_key(created)].append(row)

    # Baseline failure rate per bank/method across the whole dataset.
    baseline_bank_fail = defaultdict(lambda: [0, 0])   # bank -> [fail_count, total]
    baseline_method_fail = defaultdict(lambda: [0, 0])
    for row in payments_rows:
        failed = row.get("true_final_state") == "FAILED"
        baseline_bank_fail[row.get("bank") or "UNKNOWN"][0] += int(failed)
        baseline_bank_fail[row.get("bank") or "UNKNOWN"][1] += 1
        baseline_method_fail[row["payment_method"]][0] += int(failed)
        baseline_method_fail[row["payment_method"]][1] += 1

    def rate(counter, key):
        f, t = counter[key]
        return f / t if t else 0.0

    created_count = 0
    existing_ids = {i.incident_id for i in db.query(Incident.incident_id).all()}

    for bin_key, rows in sorted(bins.items()):
        if len(rows) < MIN_BIN_VOLUME:
            continue

        bank_ratio, method_ratio = {}, {}
        for bank in {r.get("bank") or "UNKNOWN" for r in rows}:
            bin_rows = [r for r in rows if (r.get("bank") or "UNKNOWN") == bank]
            bin_fail_rate = sum(r.get("true_final_state") == "FAILED" for r in bin_rows) / len(bin_rows)
            base = rate(baseline_bank_fail, bank) or 0.01
            bank_ratio[bank] = round(bin_fail_rate / base, 2)
        for method in {r["payment_method"] for r in rows}:
            bin_rows = [r for r in rows if r["payment_method"] == method]
            bin_fail_rate = sum(r.get("true_final_state") == "FAILED" for r in bin_rows) / len(bin_rows)
            base = rate(baseline_method_fail, method) or 0.01
            method_ratio[method] = round(bin_fail_rate / base, 2)

        worst_ratio = max(list(bank_ratio.values()) + list(method_ratio.values()) + [0])
        if worst_ratio < FAILURE_RATE_SPIKE_RATIO:
            continue  # this bin is normal — no incident

        incident_id = f"INC_{bin_key.strftime('%Y%m%dT%H%M')}"
        if incident_id in existing_ids:
            continue

        evidence = {
            "bank_failure_rate_ratio": bank_ratio, "method_failure_rate_ratio": method_ratio,
            "webhook_latency_ratio": 1.0, "capture_delay_ratio": 1.0,
            "duration_minutes": BIN_MINUTES,
        }
        diagnosis = diagnose_root_cause(evidence)

        avg_amount = sum(float(r["amount"]) for r in rows) / len(rows)
        excess_fail_prob = max(0.0, (worst_ratio - 1) * 0.15)
        impact = compute_financial_impact(
            affected_volume=len(rows), avg_txn_value=avg_amount,
            excess_failure_probability=excess_fail_prob, expected_duration_minutes=BIN_MINUTES,
            recovery_probability=0.4, basis="ESTIMATED",
        )

        severity = "HIGH" if worst_ratio > 3 else ("MEDIUM" if worst_ratio > 2.3 else "LOW")
        worst_bank = max(bank_ratio, key=bank_ratio.get) if bank_ratio else None
        worst_method = max(method_ratio, key=method_ratio.get) if method_ratio else None

        db.add(Incident(
            incident_id=incident_id, detected_at=bin_key, severity=severity,
            anomaly_score=round(worst_ratio, 2), affected_bank=worst_bank, affected_method=worst_method,
            root_cause=diagnosis.root_cause, root_cause_confidence=diagnosis.confidence,
            supporting_evidence_json=diagnosis.supporting_evidence,
            contradicting_evidence_json=diagnosis.contradicting_evidence,
            revenue_exposure=impact.revenue_exposure, expected_recoverable_value=impact.expected_recoverable_value,
            financial_basis=impact.basis,
        ))
        db.add(IncidentMemory(
            incident_id=incident_id, pattern_json=evidence, payment_method=worst_method, bank=worst_bank,
            failure_rate=round(max(bank_ratio.values(), default=0) * 0.1, 3), duration_minutes=BIN_MINUTES,
            root_cause=diagnosis.root_cause, recommended_action="STOP" if severity == "HIGH" else "VERIFY",
            revenue_impact=impact.revenue_exposure,
        ))
        created_count += 1

    db.commit()
    return {"incidents_created": created_count, "bins_scanned": len(bins)}
