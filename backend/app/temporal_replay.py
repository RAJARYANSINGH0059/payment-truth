"""
Temporal Replay (spec sections 59-60) — the feature the spec calls
"mandatory" and "one of the most important demo features," because it's
the single clearest way to show a judge the core idea in seconds: a
payment's true state and what the merchant actually knew at each moment
in time are two different things.

Reads directly from the generator's own CSVs (data/demo/*.csv) rather
than the DB, because simulation-loaded payments never get PaymentEvent
DB rows (only webhook-sourced ones do — see simulation_loader.py) while
the CSVs already carry everything needed: true event_time vs.
received_time, duplicate/out-of-order flags, and every observation
snapshot. This mirrors how generate_dataset.py's own --demo flag already
prints a text version of this exact story to the console.
"""
import csv
import os
from datetime import datetime


def _read_csv(path):
    if not os.path.exists(path):
        return []
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def build_replay(payment_id: str, data_dir: str) -> dict | None:
    """Returns None if this payment isn't in the current data/demo/*.csv
    files — expected if the dataset has been regenerated since, or if
    this payment came from a webhook/CSV-upload rather than the
    simulator. Never fabricates a replay for a payment it can't actually
    reconstruct."""
    payments = _read_csv(os.path.join(data_dir, "payments.csv"))
    payment_row = next((p for p in payments if p["payment_id"] == payment_id), None)
    if payment_row is None:
        return None

    events = _read_csv(os.path.join(data_dir, "payment_events.csv"))
    payment_events = [e for e in events if e["payment_id"] == payment_id]
    payment_events.sort(key=lambda e: e["received_time"])

    snapshots = _read_csv(os.path.join(data_dir, "observation_snapshots.csv"))
    payment_snapshots = [s for s in snapshots if s["payment_id"] == payment_id]
    payment_snapshots.sort(key=lambda s: s["observation_at"])

    timeline = [{
        "event_time": e["event_time"], "received_time": e["received_time"],
        "event_type": e["event_type"],
        "duplicate": e["duplicate_flag"].lower() == "true",
        "out_of_order": e["out_of_order_flag"].lower() == "true",
    } for e in payment_events]

    snapshot_story = [{
        "observation_at": s["observation_at"],
        "seconds_after_creation": s.get("time_since_payment_sec"),
        "observed_status": s["observed_status_at_snapshot"],
        "events_known_at_this_point": s["event_count"],
    } for s in payment_snapshots]

    last_snapshot_status = payment_snapshots[-1]["observed_status_at_snapshot"] if payment_snapshots else None
    final_truth = payment_row.get("true_final_state")
    final_observed = payment_row.get("final_observed_state")

    return {
        "payment_id": payment_id,
        "scenario": payment_row.get("scenario"),
        "true_world": {
            "created_at": payment_row.get("created_at"),
            "resolved_at": payment_row.get("resolved_at"),
            "final_true_state": final_truth,
        },
        "event_delivery_timeline": timeline,
        "observation_snapshots": snapshot_story,
        "ground_truth_revealed_later": {
            "final_observed_state": final_observed,
            "note": ("This is only knowable in hindsight — at every earlier snapshot above, "
                     "only 'observed_status' was actually available."),
        },
        "naive_last_known_status_vs_truth": {
            "last_known_before_resolution": last_snapshot_status,
            "actual_final_state": final_observed,
            "matched": last_snapshot_status == final_observed if last_snapshot_status else None,
        },
    }
