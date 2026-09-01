#!/usr/bin/env python3
"""
Incident Memory A/B experiment (completion-prompt sections 8-10).

Variant A: root-cause diagnosis with NO historical similarity evidence.
Variant B: same diagnosis, but with a "similar_historical_incident" hint
           supplied whenever an earlier incident in the same run (processed
           in temporal order, so "earlier" is real, not a data-leak) is a
           strong structured match via historical_similarity.find_similar_incidents.

Ground truth for scoring comes from incidents_truth.csv (the simulator's
own hidden incident cause), never fed to the diagnosis function itself —
only used afterward to check top-1/top-3 accuracy.

Usage:
    python experiments/incident_memory/run.py
"""
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime

import pandas as pd

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, os.path.join(REPO_ROOT, "backend"))
from app.decision_engine import diagnose_root_cause, decide  # noqa: E402
from app.historical_similarity import find_similar_incidents  # noqa: E402

EXPERIMENT_DIR = os.path.dirname(__file__)
DATA_DIR = os.path.join(EXPERIMENT_DIR, "_data")

CAUSE_TO_EXPECTED_DIAGNOSIS = {
    "BANK_DEGRADATION": "BANK_SPECIFIC",
    "PAYMENT_METHOD_DEGRADATION": "PAYMENT_METHOD_SPECIFIC",
    "WEBHOOK_PROCESSING_DEGRADATION": "WEBHOOK_PROCESSING",
    "MERCHANT_CONFIGURATION": "MERCHANT_SPECIFIC",
    # SYSTEMIC has no single-category match in ROOT_CAUSES — excluded from
    # top-1 scoring below and reported honestly rather than force-mapped.
}

BIN_MINUTES = 10


def generate(config_name: str, seed: int, payments: int, sim_days: int):
    subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "scripts", "generate_dataset.py"),
         "--payments", str(payments), "--seed", str(seed), "--sim-days", str(sim_days),
         "--config", config_name, "--out-dir", DATA_DIR],
        check=True, capture_output=True, text=True,
    )


def compute_evidence_for_window(payments_df, start, end, baseline_bank, baseline_method):
    window = payments_df[(payments_df["created_at"] >= start) & (payments_df["created_at"] <= end)]
    if len(window) < 5:
        return None
    bank_ratio, method_ratio = {}, {}
    for bank in window["bank"].unique():
        rows = window[window["bank"] == bank]
        fail_rate = (rows["true_final_state"] == "FAILED").mean()
        base = baseline_bank.get(bank, 0.05) or 0.01
        bank_ratio[bank] = round(fail_rate / base, 2)
    for method in window["payment_method"].unique():
        rows = window[window["payment_method"] == method]
        fail_rate = (rows["true_final_state"] == "FAILED").mean()
        base = baseline_method.get(method, 0.05) or 0.01
        method_ratio[method] = round(fail_rate / base, 2)
    return {
        "bank_failure_rate_ratio": bank_ratio, "method_failure_rate_ratio": method_ratio,
        "webhook_latency_ratio": 1.0, "capture_delay_ratio": 1.0,
        "duration_minutes": (end - start).total_seconds() / 60,
    }


def main():
    config = {"config": "stress", "seed": 55, "payments": 12000, "sim_days": 15}
    print("Generating dataset with multiple incidents (stress config for incident density)...")
    generate(config["config"], config["seed"], config["payments"], config["sim_days"])

    payments_df = pd.read_csv(os.path.join(DATA_DIR, "payments.csv"), parse_dates=["created_at"])
    incidents_truth = pd.read_csv(os.path.join(DATA_DIR, "incidents_truth.csv"), parse_dates=["start", "end"])
    incidents_truth = incidents_truth.sort_values("start")

    baseline_bank = {b: (payments_df[payments_df["bank"] == b]["true_final_state"] == "FAILED").mean()
                      for b in payments_df["bank"].unique()}
    baseline_method = {m: (payments_df[payments_df["payment_method"] == m]["true_final_state"] == "FAILED").mean()
                        for m in payments_df["payment_method"].unique()}

    memory: list[dict] = []  # grows as we process incidents in time order
    results_a, results_b = [], []  # variant A (no memory), variant B (with memory)
    skipped_systemic, skipped_low_volume = 0, 0

    for _, inc in incidents_truth.iterrows():
        expected = CAUSE_TO_EXPECTED_DIAGNOSIS.get(inc["cause"])
        evidence = compute_evidence_for_window(payments_df, inc["start"], inc["end"], baseline_bank, baseline_method)
        if evidence is None:
            skipped_low_volume += 1
            continue

        # Variant A: no memory.
        diag_a = diagnose_root_cause(evidence)

        # Variant B: consult memory of earlier-processed incidents only.
        current_features = {
            "payment_method": max(evidence["method_failure_rate_ratio"], key=evidence["method_failure_rate_ratio"].get)
                                if evidence["method_failure_rate_ratio"] else None,
            "bank": max(evidence["bank_failure_rate_ratio"], key=evidence["bank_failure_rate_ratio"].get)
                                if evidence["bank_failure_rate_ratio"] else None,
            "root_cause": diag_a.root_cause,
            "failure_rate": max(list(evidence["bank_failure_rate_ratio"].values()) or [0]) * 0.1,
            "duration_minutes": evidence["duration_minutes"],
        }
        similar = find_similar_incidents(current_features, memory, top_n=1) if memory else []
        evidence_b = dict(evidence)
        if similar and similar[0].similarity_pct > 50:
            evidence_b["similar_historical_incident"] = f"{similar[0].incident_id} ({similar[0].similarity_pct}% similar)"
        diag_b = diagnose_root_cause(evidence_b)

        if expected is not None:
            results_a.append({"expected": expected, "diagnosed": diag_a.root_cause, "confidence": diag_a.confidence})
            results_b.append({"expected": expected, "diagnosed": diag_b.root_cause, "confidence": diag_b.confidence})
        else:
            skipped_systemic += 1

        # Add this incident to memory for subsequent (later) incidents.
        memory.append({
            "incident_id": inc["incident_id"], "payment_method": current_features["payment_method"],
            "bank": current_features["bank"], "root_cause": diag_a.root_cause,
            "failure_rate": current_features["failure_rate"], "duration_minutes": current_features["duration_minutes"],
            "recommended_action": "STOP" if diag_a.confidence > 0.5 else "VERIFY",
            "actual_outcome": inc["cause"], "revenue_impact": None,
        })

    def top1_accuracy(results):
        if not results:
            return None
        return round(sum(1 for r in results if r["diagnosed"] == r["expected"]) / len(results), 4)

    def avg_confidence(results):
        if not results:
            return None
        return round(sum(r["confidence"] for r in results) / len(results), 4)

    report = {
        "experiment": "incident_memory_ab",
        "config": config,
        "n_incidents_total": len(incidents_truth),
        "n_scored_incidents": len(results_a),
        "skipped_low_volume_window": skipped_low_volume,
        "skipped_systemic_no_category_match": skipped_systemic,
        "without_memory": {
            "root_cause_top1_accuracy": top1_accuracy(results_a),
            "average_confidence": avg_confidence(results_a),
        },
        "with_memory": {
            "root_cause_top1_accuracy": top1_accuracy(results_b),
            "average_confidence": avg_confidence(results_b),
        },
        "accuracy_improvement": (
            round(top1_accuracy(results_b) - top1_accuracy(results_a), 4)
            if results_a and results_b else None
        ),
        "confidence_improvement": (
            round(avg_confidence(results_b) - avg_confidence(results_a), 4)
            if results_a and results_b else None
        ),
        "note": ("The decision engine's WAIT/VERIFY/RECOVER/STOP output does not currently "
                 "take diagnosed root cause as an input (severity/financial exposure drive it "
                 "instead), so decision accuracy is identical between variants by construction — "
                 "reported honestly rather than a fabricated difference. Memory's measured effect "
                 "here is limited to root-cause confidence/accuracy, not the final action taken."),
    }

    with open(os.path.join(EXPERIMENT_DIR, "metrics.json"), "w") as f:
        json.dump(report, f, indent=2)

    print(json.dumps({k: v for k, v in report.items() if k not in ("note",)}, indent=2))


if __name__ == "__main__":
    main()
