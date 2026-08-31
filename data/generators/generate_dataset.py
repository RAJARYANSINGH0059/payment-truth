#!/usr/bin/env python3
"""
Payment Truth — synthetic temporal event simulator (Phase 1).

Generates THREE linked tables that make the TRUE WORLD / OBSERVED WORLD
separation (spec section 4) explicit and inspectable:

  payments.csv              — true world: one row per payment, true state
                               timeline + eventual ground truth
  payment_events.csv        — the discrete events a real webhook system
                               would emit, each with a true event_time AND
                               a separately-simulated received_time
  observation_snapshots.csv — multiple "what did the merchant know as of
                               time T" rows per payment (the actual ML
                               training/eval unit — section 27)

Everything is reproducible: same --seed + --config → same dataset
(section 44). Run with --demo to print one full chronological replay of
a single payment (section 5 / section 73 acceptance demonstration).

Usage:
    python generate_dataset.py --payments 10000 --seed 42
    python generate_dataset.py --payments 500 --seed 42 --demo
"""
import argparse
import csv
import hashlib
import json
import math
import os
import random
import sys
from dataclasses import dataclass, field, asdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from data.schemas.leakage_columns import LEAKAGE_COLUMNS  # noqa: E402

GENERATOR_VERSION = "0.1.0"

PAYMENT_METHODS = ["UPI", "CARD", "NETBANKING", "WALLET"]
BANKS = ["BANK_A", "BANK_B", "BANK_C", "BANK_D", "BANK_E"]
CUSTOMER_TYPES = ["new", "repeat", "high_frequency", "low_frequency",
                   "normally_successful", "failure_prone", "high_value"]
MERCHANT_TYPES = ["small", "high_volume", "high_ticket", "upi_heavy",
                   "card_heavy", "subscription_heavy", "stable", "volatile"]
INCIDENT_CAUSES = ["BANK_DEGRADATION", "PAYMENT_METHOD_DEGRADATION",
                    "WEBHOOK_PROCESSING_DEGRADATION", "MERCHANT_CONFIGURATION",
                    "SYSTEMIC"]

# Observation offsets in seconds after payment creation (section 11).
SNAPSHOT_OFFSETS_SEC = [5, 15, 30, 60, 180, 600]

TRUE_STATES = ["CREATED", "ATTEMPTED", "AUTHORIZED", "CAPTURED", "FAILED", "REFUNDED"]
OBSERVED_STATES = ["UNKNOWN", "PENDING", "FAILED", "SUCCESS"]

EVENT_TO_OBSERVED_PRECEDENCE = {
    # Higher number wins when multiple known events conflict — mirrors a
    # realistic resolver that treats "captured" as authoritative over an
    # earlier-looking "failed" signal, rather than naively taking whichever
    # event arrived last (section 15: order must not decide truth).
    "payment.captured": (4, "SUCCESS"),
    "order.paid": (4, "SUCCESS"),
    "payment.authorized": (2, "PENDING"),
    "payment.failed": (1, "FAILED"),
}


def config_hash(cfg: dict) -> str:
    return hashlib.sha256(json.dumps(cfg, sort_keys=True).encode()).hexdigest()[:12]


@dataclass
class Bank:
    name: str
    base_failure_rate: float
    base_latency_ms: float


@dataclass
class Merchant:
    id: str
    type: str
    method_mix: dict


@dataclass
class Customer:
    id: str
    type: str
    prior_payment_count: int
    prior_success_rate: float


@dataclass
class Incident:
    id: str
    cause: str
    bank: str | None
    method: str | None
    start: datetime
    end: datetime
    severity: float  # 0..1, added to failure probability / latency during window

    def active_at(self, t: datetime) -> float:
        """Returns a 0..1 intensity multiplier following RAMP_UP/PEAK/RECOVERY
        (section 25) rather than an on/off step."""
        if t < self.start or t > self.end:
            return 0.0
        span = (self.end - self.start).total_seconds()
        pos = (t - self.start).total_seconds() / max(span, 1)
        # ramp up 0->0.3, peak 0.3->0.7, recovery 0.7->1.0
        if pos < 0.3:
            return self.severity * (pos / 0.3)
        elif pos < 0.7:
            return self.severity
        else:
            return self.severity * (1 - (pos - 0.7) / 0.3)


def build_banks(rng: random.Random) -> list[Bank]:
    banks = []
    for b in BANKS:
        banks.append(Bank(
            name=b,
            base_failure_rate=rng.uniform(0.03, 0.09),
            base_latency_ms=rng.uniform(400, 1500),
        ))
    return banks


def build_merchants(rng: random.Random, n=25) -> list[Merchant]:
    merchants = []
    for i in range(n):
        mtype = rng.choice(MERCHANT_TYPES)
        mix = {m: rng.random() for m in PAYMENT_METHODS}
        if mtype == "upi_heavy":
            mix["UPI"] *= 3
        if mtype == "card_heavy":
            mix["CARD"] *= 3
        total = sum(mix.values())
        mix = {k: v / total for k, v in mix.items()}
        merchants.append(Merchant(id=f"M{i:04d}", type=mtype, method_mix=mix))
    return merchants


def build_customers(rng: random.Random, n=4000) -> list[Customer]:
    customers = []
    for i in range(n):
        ctype = rng.choice(CUSTOMER_TYPES)
        prior_count = max(0, int(rng.gauss(8, 12))) if ctype != "new" else 0
        base_rate = {
            "normally_successful": rng.uniform(0.9, 0.98),
            "failure_prone": rng.uniform(0.55, 0.75),
        }.get(ctype, rng.uniform(0.8, 0.95))
        customers.append(Customer(id=f"C{i:06d}", type=ctype,
                                   prior_payment_count=prior_count,
                                   prior_success_rate=round(base_rate, 3)))
    return customers


def build_incidents(rng: random.Random, sim_start: datetime, sim_days: int) -> list[Incident]:
    """A handful of latent incidents scattered across the simulated period.
    Cause is NEVER exposed as a feature (see leakage_columns.py); only its
    downstream symptoms (failure-rate/latency shifts) are observable."""
    incidents = []
    n_incidents = max(2, sim_days // 3)
    for i in range(n_incidents):
        cause = rng.choice(INCIDENT_CAUSES)
        start_offset_days = rng.uniform(0, sim_days - 0.5)
        start = sim_start + timedelta(days=start_offset_days)
        duration_min = rng.uniform(10, 240)
        end = start + timedelta(minutes=duration_min)
        incidents.append(Incident(
            id=f"INC{i:04d}",
            cause=cause,
            bank=rng.choice(BANKS) if cause == "BANK_DEGRADATION" else None,
            method=rng.choice(PAYMENT_METHODS) if cause == "PAYMENT_METHOD_DEGRADATION" else None,
            start=start, end=end,
            severity=rng.uniform(0.15, 0.55),
        ))
    # A few "hard negative" traffic spikes with NO incident behind them
    # (section 26) — tagged only for eval, never given to the model.
    return incidents


def incident_effect(incidents: list[Incident], t: datetime, bank: str, method: str, merchant: Merchant):
    """Sum of active incident intensities relevant to this payment.
    Returns (failure_bump, latency_bump_ms, active_incident_id_or_None)."""
    failure_bump, latency_bump, active_id = 0.0, 0.0, None
    for inc in incidents:
        intensity = inc.active_at(t)
        if intensity <= 0:
            continue
        relevant = False
        if inc.cause == "BANK_DEGRADATION" and inc.bank == bank:
            relevant = True
        elif inc.cause == "PAYMENT_METHOD_DEGRADATION" and inc.method == method:
            relevant = True
        elif inc.cause in ("WEBHOOK_PROCESSING_DEGRADATION", "SYSTEMIC"):
            relevant = True
        elif inc.cause == "MERCHANT_CONFIGURATION" and rng_merchant_hit(merchant, inc):
            relevant = True
        if relevant:
            failure_bump += intensity * 0.35
            latency_bump += intensity * 3000
            active_id = inc.id
    return min(failure_bump, 0.9), latency_bump, active_id


def rng_merchant_hit(merchant: Merchant, inc: Incident) -> bool:
    # Deterministic-ish pseudo-hash so a MERCHANT_CONFIGURATION incident
    # consistently affects the same subset of merchants without needing
    # extra RNG state threaded through.
    return int(hashlib.md5(f"{merchant.id}{inc.id}".encode()).hexdigest(), 16) % 5 == 0


def sample_delivery_delay(rng: random.Random, base_latency_ms: float, latency_bump_ms: float) -> float:
    """Lognormal-ish delay: common fast events, a delayed tail, rare severe
    delays (section 13). Not claimed to be measured Razorpay production data
    — an explicitly documented synthetic assumption (see docs/ASSUMPTIONS.md)."""
    mu = math.log(max(base_latency_ms + latency_bump_ms, 50))
    sigma = 0.6
    delay_ms = rng.lognormvariate(mu, sigma)
    if rng.random() < 0.02:  # rare severe delay tail
        delay_ms += rng.uniform(15000, 60000)
    return delay_ms


def simulate_payment(rng: random.Random, idx: int, banks, merchants, customers,
                      incidents, sim_start: datetime, sim_days: int):
    created_at = sim_start + timedelta(seconds=rng.uniform(0, sim_days * 86400))
    merchant = rng.choice(merchants)
    customer = rng.choice(customers)
    method = rng.choices(PAYMENT_METHODS, weights=[merchant.method_mix[m] for m in PAYMENT_METHODS])[0]
    bank = rng.choice(banks)
    amount = round(math.exp(rng.gauss(6.5, 1.1)), 2)  # long-tailed INR amounts

    fail_bump, latency_bump, incident_id = incident_effect(incidents, created_at, bank.name, method, merchant)

    base_fail_p = bank.base_failure_rate + (1 - customer.prior_success_rate) * 0.15
    fail_p = min(0.97, max(0.01, base_fail_p + fail_bump + rng.gauss(0, 0.02)))

    # --- TRUE WORLD outcome path ---
    scenario = None
    is_hard_negative = False
    events = []  # (event_type, true_time)
    t = created_at
    events.append(("payment.attempted", t))

    roll = rng.random()
    if roll < fail_p:
        # genuine failure
        t = t + timedelta(seconds=rng.uniform(1, 8))
        events.append(("payment.failed", t))
        true_final_state = "FAILED"
        final_observed_state = "FAILED"
        scenario = "genuine_failure"
    else:
        t_auth = t + timedelta(seconds=rng.uniform(1, 6))
        events.append(("payment.authorized", t_auth))
        # small chance of late capture: observed side sees a failure-like
        # signal or long pending gap before the true capture lands.
        if rng.random() < 0.08:
            scenario = "late_capture"
            capture_delay = rng.uniform(30, 400)
            t_cap = t_auth + timedelta(seconds=capture_delay)
            # inject a misleading early failed-looking event some of the time
            if rng.random() < 0.5:
                t_mid = t_auth + timedelta(seconds=rng.uniform(3, 10))
                events.append(("payment.failed", t_mid))  # transient/misleading
            events.append(("payment.captured", t_cap))
            true_final_state = "CAPTURED"
            final_observed_state = "SUCCESS"
        else:
            t_cap = t_auth + timedelta(seconds=rng.uniform(1, 5))
            events.append(("payment.captured", t_cap))
            true_final_state = "CAPTURED"
            final_observed_state = "SUCCESS"
            scenario = "normal_success"

    if scenario == "normal_success" and fail_bump < 0.05 and rng.random() < 0.15:
        # hard negative: a traffic-normal payment during a *quiet* window,
        # tagged so eval can check the model doesn't cry wolf.
        is_hard_negative = True

    resolved_at = events[-1][1]
    time_to_resolution_sec = (resolved_at - created_at).total_seconds()

    payment_row = {
        "payment_id": f"P{idx:07d}",
        "order_id": f"O{idx:07d}",
        "customer_id": customer.id,
        "merchant_id": merchant.id,
        "amount": amount,
        "currency": "INR",
        "payment_method": method,
        "bank": bank.name,
        "created_at": created_at.isoformat(),
        "source": "SYNTHETIC",
        # --- leakage columns (evaluation-only, see leakage_columns.py) ---
        "true_final_state": true_final_state,
        "final_observed_state": final_observed_state,
        "resolved_at": resolved_at.isoformat(),
        "time_to_resolution_sec": round(time_to_resolution_sec, 2),
        "scenario": scenario,
        "incident_id": incident_id,
        "is_hard_negative": is_hard_negative,
    }

    # --- Event delivery simulation (separate from true event creation) ---
    event_rows = []
    for seq, (etype, etime) in enumerate(events):
        delay_ms = sample_delivery_delay(rng, bank.base_latency_ms, latency_bump)
        received = etime + timedelta(milliseconds=delay_ms)
        event_id = f"EV{idx:07d}{seq:02d}"
        event_rows.append({
            "event_id": event_id, "payment_id": payment_row["payment_id"],
            "event_type": etype, "event_time": etime.isoformat(),
            "received_time": received.isoformat(), "sequence_number": seq,
            "duplicate_flag": False, "out_of_order_flag": False,
            "source": "SYNTHETIC",
        })
        # duplicate delivery (section 14): independent extra copy, arrives later
        if rng.random() < 0.06:
            dup_delay_ms = sample_delivery_delay(rng, bank.base_latency_ms, latency_bump)
            dup_received = received + timedelta(milliseconds=dup_delay_ms * 0.3 + 200)
            event_rows.append({
                "event_id": f"{event_id}D", "payment_id": payment_row["payment_id"],
                "event_type": etype, "event_time": etime.isoformat(),
                "received_time": dup_received.isoformat(), "sequence_number": seq,
                "duplicate_flag": True, "out_of_order_flag": False,
                "source": "SYNTHETIC",
            })

    # out-of-order delivery (section 15): swap received_time of two events
    if len(event_rows) >= 2 and rng.random() < 0.10:
        a, b = rng.sample(range(len(event_rows)), 2)
        event_rows[a]["received_time"], event_rows[b]["received_time"] = \
            event_rows[b]["received_time"], event_rows[a]["received_time"]
        event_rows[a]["out_of_order_flag"] = True
        event_rows[b]["out_of_order_flag"] = True

    return payment_row, event_rows, customer, merchant


def resolve_observed_status(known_events: list[dict]) -> str:
    """Resolver that must NOT simply trust arrival order (section 15)."""
    if not known_events:
        return "UNKNOWN"
    best_rank, best_status = -1, "PENDING"
    for e in known_events:
        rank, status = EVENT_TO_OBSERVED_PRECEDENCE.get(e["event_type"], (0, "PENDING"))
        if rank > best_rank:
            best_rank, best_status = rank, status
    return best_status


def build_snapshots(payment_row: dict, event_rows: list[dict], customer: Customer, merchant: Merchant):
    created_at = datetime.fromisoformat(payment_row["created_at"])
    snapshots = []
    for offset in SNAPSHOT_OFFSETS_SEC:
        obs_at = created_at + timedelta(seconds=offset)
        known = [e for e in event_rows if datetime.fromisoformat(e["received_time"]) <= obs_at]
        if not known:
            continue  # nothing observable yet at this offset — skip, not a row
        observed_status = resolve_observed_status(known)
        last_event_recv = max(datetime.fromisoformat(e["received_time"]) for e in known)
        dup_count = sum(1 for e in known if e["duplicate_flag"])
        ooo_flag = any(e["out_of_order_flag"] for e in known)

        snapshots.append({
            "payment_id": payment_row["payment_id"],
            "observation_at": obs_at.isoformat(),
            "observed_status_at_snapshot": observed_status,
            "amount": payment_row["amount"],
            "payment_method": payment_row["payment_method"],
            "bank": payment_row["bank"],
            "hour_of_day": created_at.hour,
            "day_of_week": created_at.weekday(),
            "previous_payment_count": customer.prior_payment_count,
            "previous_success_rate": customer.prior_success_rate,
            "merchant_type": merchant.type,
            "event_count": len(known),
            "duplicate_event_count": dup_count,
            "event_order_anomaly": ooo_flag,
            "time_since_payment_sec": offset,
            "time_since_last_event_sec": round((obs_at - last_event_recv).total_seconds(), 2),
            "source": "SYNTHETIC",
            # --- leakage columns (label + provenance, evaluation-only) ---
            "true_final_state": payment_row["true_final_state"],
            "final_observed_state": payment_row["final_observed_state"],
            "resolved_at": payment_row["resolved_at"],
            "time_to_resolution_sec": payment_row["time_to_resolution_sec"],
            "scenario": payment_row["scenario"],
            "incident_id": payment_row["incident_id"],
            "is_hard_negative": payment_row["is_hard_negative"],
        })
    return snapshots


def validate(payments, events, snapshots):
    """Section 45: pre-training data quality gate."""
    problems = []
    pids = set(p["payment_id"] for p in payments)
    if len(pids) != len(payments):
        problems.append("duplicate payment_id detected")
    eids = [e["event_id"] for e in events]
    if len(set(eids)) != len(eids):
        problems.append("duplicate event_id detected")
    for e in events:
        if e["payment_id"] not in pids:
            problems.append(f"event {e['event_id']} references unknown payment {e['payment_id']}")
            break
    for p in payments:
        if p["true_final_state"] not in TRUE_STATES:
            problems.append(f"invalid true_final_state on {p['payment_id']}")
            break
    for s in snapshots:
        if datetime.fromisoformat(s["observation_at"]) < datetime.fromisoformat(
                [p for p in payments if p["payment_id"] == s["payment_id"]][0]["created_at"]):
            problems.append(f"snapshot before creation on {s['payment_id']}")
            break
    return problems


def write_csv(path, rows):
    if not rows:
        return
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def print_replay(payment_row, event_rows, snapshots):
    print("=" * 70)
    print(f"TEMPORAL REPLAY — {payment_row['payment_id']}  (scenario={payment_row['scenario']})")
    print("=" * 70)
    print(f"\nTRUE WORLD:\n  final true state = {payment_row['true_final_state']}")
    print(f"  created_at       = {payment_row['created_at']}")
    print(f"  resolved_at      = {payment_row['resolved_at']}")

    print("\nEVENT GENERATION -> DELIVERY:")
    for e in sorted(event_rows, key=lambda x: x["received_time"]):
        dup = " [DUPLICATE]" if e["duplicate_flag"] else ""
        ooo = " [OUT-OF-ORDER]" if e["out_of_order_flag"] else ""
        print(f"  event_time={e['event_time']}  received_time={e['received_time']}"
              f"  type={e['event_type']}{dup}{ooo}")

    print("\nOBSERVATION SNAPSHOTS (what the merchant knew at each point):")
    for s in snapshots:
        print(f"  T+{s['time_since_payment_sec']:>4}s  observed_status={s['observed_status_at_snapshot']:<8}"
              f"  events_known={s['event_count']}  dup={s['duplicate_event_count']}"
              f"  order_anomaly={s['event_order_anomaly']}")

    print(f"\nGROUND TRUTH (only revealed after resolution): {payment_row['true_final_state']}")

    last_snap = snapshots[-2] if len(snapshots) > 1 else snapshots[0]
    naive_pred = last_snap["observed_status_at_snapshot"]
    actual = payment_row["final_observed_state"]
    verdict = "CORRECT" if naive_pred == actual else "INCORRECT"
    print(f"\nEVALUATION (naive last-known-status baseline, NOT the trained model):")
    print(f"  prediction (at T+{last_snap['time_since_payment_sec']}s) = {naive_pred}")
    print(f"  actual final observed state                = {actual}")
    print(f"  verdict                                     = {verdict}")
    print("=" * 70)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--payments", type=int, default=10000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--config", type=str, default="default")
    ap.add_argument("--sim-days", type=int, default=30)
    ap.add_argument("--out-dir", type=str, default=None)
    ap.add_argument("--demo", action="store_true", help="print one full temporal replay and exit early")
    args = ap.parse_args()

    cfg = {"payments": args.payments, "seed": args.seed, "config": args.config, "sim_days": args.sim_days}
    cfg_hash = config_hash(cfg)
    rng = random.Random(args.seed)

    sim_start = datetime(2026, 1, 1)
    banks = build_banks(rng)
    merchants = build_merchants(rng)
    customers = build_customers(rng)
    incidents = build_incidents(rng, sim_start, args.sim_days)

    payments, events, snapshots = [], [], []
    demo_candidates = {"late_capture": None, "genuine_failure": None}

    for i in range(args.payments):
        p, e, cust, merch = simulate_payment(rng, i, banks, merchants, customers,
                                              incidents, sim_start, args.sim_days)
        s = build_snapshots(p, e, cust, merch)
        payments.append(p)
        events.extend(e)
        snapshots.extend(s)
        if p["scenario"] in demo_candidates and demo_candidates[p["scenario"]] is None and len(s) >= 2:
            demo_candidates[p["scenario"]] = (p, e, s)

    print(f"Generated {len(payments)} payments, {len(events)} events, "
          f"{len(snapshots)} observation snapshots.")
    print(f"generator_version={GENERATOR_VERSION} config_hash={cfg_hash} seed={args.seed}")

    problems = validate(payments, events, snapshots)
    if problems:
        print("\nDATA QUALITY: FAILED")
        for pr in problems:
            print(f"  - {pr}")
        sys.exit(1)
    print("DATA QUALITY: PASS (no duplicate IDs, no invalid states, no pre-creation snapshots)")

    scenario_counts = {}
    for p in payments:
        scenario_counts[p["scenario"]] = scenario_counts.get(p["scenario"], 0) + 1
    print("\nScenario distribution:")
    for k, v in sorted(scenario_counts.items()):
        print(f"  {k:<20} {v:>6}  ({100*v/len(payments):.1f}%)")

    incident_hits = sum(1 for p in payments if p["incident_id"])
    hard_neg = sum(1 for p in payments if p["is_hard_negative"])
    print(f"\nPayments touched by an incident window: {incident_hits} ({100*incident_hits/len(payments):.1f}%)")
    print(f"Hard-negative payments (normal but noisy): {hard_neg} ({100*hard_neg/len(payments):.1f}%)")

    if args.demo:
        for scen, cand in demo_candidates.items():
            if cand:
                print_replay(*cand)
        return

    out_dir = args.out_dir or os.path.join(os.path.dirname(__file__), "..", "demo")
    os.makedirs(out_dir, exist_ok=True)
    write_csv(os.path.join(out_dir, "payments.csv"), payments)
    write_csv(os.path.join(out_dir, "payment_events.csv"), events)
    write_csv(os.path.join(out_dir, "observation_snapshots.csv"), snapshots)
    print(f"\nWrote payments.csv, payment_events.csv, observation_snapshots.csv to {out_dir}")

    leak_check_cols = set(snapshots[0].keys()) if snapshots else set()
    print(f"\nLeakage columns present in snapshots (evaluation-only, must be dropped before "
          f"feature-building): {sorted(LEAKAGE_COLUMNS.intersection(leak_check_cols))}")


if __name__ == "__main__":
    main()
