"""
Payment Truth — Phase 6: root-cause + financial-impact + decision engines.

All three are deterministic and auditable (spec sections 12/39/40): given
the same evidence, they always produce the same output, and every output
carries its supporting/contradicting evidence so it can be inspected. None
of this touches an LLM — an LLM may narrate these outputs in prose later,
never compute them.
"""
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# ROOT-CAUSE ENGINE (section 12/37)
# ---------------------------------------------------------------------------

ROOT_CAUSES = ["BANK_SPECIFIC", "PAYMENT_METHOD_SPECIFIC", "MERCHANT_SPECIFIC",
               "WEBHOOK_PROCESSING", "NETWORK_LATENCY", "TEMPORARY_DEGRADATION",
               "CUSTOMER_SPECIFIC", "UNKNOWN"]


@dataclass
class RootCauseResult:
    root_cause: str
    confidence: float
    supporting_evidence: list
    contradicting_evidence: list


def diagnose_root_cause(evidence: dict) -> RootCauseResult:
    """evidence keys (all measured, none of them the simulator's hidden
    incident_id/cause — this only ever sees observable symptoms):
      bank_failure_rate_ratio: dict[bank] -> current/baseline ratio
      method_failure_rate_ratio: dict[method] -> current/baseline ratio
      merchant_failure_rate_ratio: dict[merchant] -> current/baseline ratio
      webhook_latency_ratio: float (current/baseline)
      capture_delay_ratio: float (current/baseline)
      duration_minutes: float
      similar_historical_incident: str | None
    """
    scores = {c: 0.0 for c in ROOT_CAUSES}
    support = {c: [] for c in ROOT_CAUSES}
    contra = {c: [] for c in ROOT_CAUSES}

    bank_ratios = evidence.get("bank_failure_rate_ratio", {})
    if bank_ratios:
        worst_bank, worst_ratio = max(bank_ratios.items(), key=lambda kv: kv[1])
        others_normal = all(r < 1.3 for b, r in bank_ratios.items() if b != worst_bank)
        if worst_ratio > 2.0 and others_normal:
            scores["BANK_SPECIFIC"] += min(0.6, (worst_ratio - 1) * 0.25)
            support["BANK_SPECIFIC"].append(
                f"{worst_bank} failure rate is {worst_ratio:.1f}x baseline while other banks are normal")
        elif worst_ratio > 1.5:
            scores["BANK_SPECIFIC"] += 0.15
            support["BANK_SPECIFIC"].append(f"{worst_bank} failure rate elevated ({worst_ratio:.1f}x)")
        else:
            contra["BANK_SPECIFIC"].append("no bank shows a sharp isolated failure-rate increase")

    method_ratios = evidence.get("method_failure_rate_ratio", {})
    if method_ratios:
        worst_method, worst_ratio = max(method_ratios.items(), key=lambda kv: kv[1])
        others_normal = all(r < 1.3 for m, r in method_ratios.items() if m != worst_method)
        if worst_ratio > 2.0 and others_normal:
            scores["PAYMENT_METHOD_SPECIFIC"] += min(0.6, (worst_ratio - 1) * 0.25)
            support["PAYMENT_METHOD_SPECIFIC"].append(
                f"{worst_method} failure rate is {worst_ratio:.1f}x baseline; other methods normal")
        else:
            contra["PAYMENT_METHOD_SPECIFIC"].append("no single payment method isolated from the rest")

    merch_ratios = evidence.get("merchant_failure_rate_ratio", {})
    if merch_ratios:
        worst_m, worst_r = max(merch_ratios.items(), key=lambda kv: kv[1])
        if worst_r > 2.0:
            scores["MERCHANT_SPECIFIC"] += min(0.5, (worst_r - 1) * 0.2)
            support["MERCHANT_SPECIFIC"].append(f"merchant {worst_m} failure rate is {worst_r:.1f}x baseline")
        else:
            contra["MERCHANT_SPECIFIC"].append("no single merchant is disproportionately affected")

    webhook_ratio = evidence.get("webhook_latency_ratio", 1.0)
    all_methods_normal = method_ratios and all(r < 1.3 for r in method_ratios.values())
    all_banks_normal = bank_ratios and all(r < 1.3 for r in bank_ratios.values())
    if webhook_ratio > 2.0 and all_methods_normal and all_banks_normal:
        scores["WEBHOOK_PROCESSING"] += min(0.6, (webhook_ratio - 1) * 0.2)
        support["WEBHOOK_PROCESSING"].append(
            f"webhook latency is {webhook_ratio:.1f}x baseline while bank/method failure rates are normal")
    elif webhook_ratio > 1.5:
        scores["WEBHOOK_PROCESSING"] += 0.15
        support["WEBHOOK_PROCESSING"].append(f"webhook latency elevated ({webhook_ratio:.1f}x)")
    else:
        contra["WEBHOOK_PROCESSING"].append("webhook latency within normal range")

    capture_ratio = evidence.get("capture_delay_ratio", 1.0)
    if capture_ratio > 1.8:
        scores["NETWORK_LATENCY"] += min(0.4, (capture_ratio - 1) * 0.15)
        support["NETWORK_LATENCY"].append(f"capture delay is {capture_ratio:.1f}x baseline")
    else:
        contra["NETWORK_LATENCY"].append("capture delay within normal range")

    duration = evidence.get("duration_minutes", 0)
    if 0 < duration < 20 and max(scores.values(), default=0) < 0.3:
        scores["TEMPORARY_DEGRADATION"] += 0.25
        support["TEMPORARY_DEGRADATION"].append(f"elevated metrics for only {duration:.0f} minutes so far")

    if evidence.get("similar_historical_incident"):
        best_cause = max(scores, key=scores.get)
        if scores[best_cause] > 0:
            scores[best_cause] += 0.1
            support[best_cause].append(
                f"similar to historical {evidence['similar_historical_incident']}")

    if all(v == 0 for v in scores.values()):
        return RootCauseResult("UNKNOWN", 0.0,
                                ["no evidence pattern matched a known root-cause signature"],
                                [])

    best = max(scores, key=scores.get)
    confidence = round(min(0.97, scores[best]), 2)
    contradicting = []
    for c, items in contra.items():
        if c != best:
            continue
        contradicting = items
    contradicting.append("no independent external confirmation")
    return RootCauseResult(best, confidence, support[best], contradicting)


# ---------------------------------------------------------------------------
# FINANCIAL IMPACT MODEL (section 11/38/40)
# ---------------------------------------------------------------------------

@dataclass
class FinancialImpact:
    revenue_exposure: float
    expected_recoverable_value: float
    basis: str  # VERIFIED / ESTIMATED / PREDICTED / SIMULATED


def compute_financial_impact(affected_volume: int, avg_txn_value: float,
                              excess_failure_probability: float, expected_duration_minutes: float,
                              recovery_probability: float, basis: str = "ESTIMATED") -> FinancialImpact:
    """
    Revenue Exposure = affected_volume * avg_txn_value * excess_failure_probability
                        * (expected_duration_minutes scaling already folded into affected_volume)
    Expected Recoverable Value = Revenue Exposure * recovery_probability

    `basis` must be one of VERIFIED / ESTIMATED / PREDICTED / SIMULATED —
    never presented as verified recovered money unless it genuinely is.
    """
    assert basis in ("VERIFIED", "ESTIMATED", "PREDICTED", "SIMULATED")
    revenue_exposure = affected_volume * avg_txn_value * excess_failure_probability
    expected_recoverable = revenue_exposure * recovery_probability
    return FinancialImpact(round(revenue_exposure, 2), round(expected_recoverable, 2), basis)


# ---------------------------------------------------------------------------
# DECISION ENGINE (section 14/39) — deterministic, only 4 outcomes
# ---------------------------------------------------------------------------

DECISIONS = ["WAIT", "VERIFY", "RECOVER", "STOP"]


def decide(p_success: float, p_pending: float, p_failed: float,
           incident_active: bool, incident_severity: float,
           txn_value: float, duplicate_risk: bool,
           confidence: float) -> str:
    """
    Deterministic rules (auditable — no ML/LLM in this function):

      STOP    — active incident at meaningful severity: don't let automatic
                recovery actions add load/risk during a live degradation.
      WAIT    — model still gives the payment a real chance to resolve to
                SUCCESS and there's no urgent reason to intervene.
      VERIFY  — evidence is genuinely mixed/low-confidence, or duplicate-
                payment risk exists — get an authoritative read before acting.
      RECOVER — failure looks genuine and confidently so, recovery is
                worth the transaction value.
    """
    if incident_active and incident_severity >= 0.25:
        return "STOP"
    if duplicate_risk:
        return "VERIFY"
    if confidence < 0.55 or (p_pending > 0.3 and abs(p_success - p_failed) < 0.2):
        return "VERIFY"
    if p_success >= 0.5 and p_success >= p_failed:
        return "WAIT"
    if p_failed >= 0.6 and confidence >= 0.55:
        return "RECOVER"
    return "VERIFY"
