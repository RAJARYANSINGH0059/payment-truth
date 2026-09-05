"""
Payment Truth — Recovery Workflow Engine.

Closes the loop the Track 3 bar asks for explicitly: "Don't just identify
the problem. Show measured money recovered across a batch, with compliant
escalation, stopping rules, and an audit trail."

Before this module, `decide()` in decision_engine.py could label a payment
RECOVER, but nothing in the app ever acted on that label — it just sat in
AuditLog as text. This module is the ACT step: it takes payments the
decision engine has already labelled RECOVER and actually executes a
bounded, auditable recovery action on each one, subject to three kinds of
guardrail so it can never become an open-ended agent:

  1. IDEMPOTENCY / RETRY CAP  — a payment can only ever get
     MAX_ATTEMPTS_PER_PAYMENT recovery attempts, ever. Once it has an
     EXECUTED or ESCALATED action, it is never touched again by this
     engine.
  2. ESCALATION THRESHOLDS    — high-value or low-confidence cases are
     never auto-executed. They are routed to ESCALATED (a human/merchant
     review queue) instead — this is the "compliant escalation" the bar
     asks for.
  3. BATCH EXPOSURE CAP       — a single batch run will not commit more
     than BATCH_EXPOSURE_CAP total transaction value to automatic
     recovery actions. Anything beyond the cap is left for the next run
     rather than acted on all at once — this is the "stopping rule".

Execution itself is honest about what kind of evidence backs each number
(same VERIFIED/ESTIMATED/PREDICTED/SIMULATED convention used everywhere
else in this repo):
  - SYNTHETIC payments: recovered_value is computed against the
    simulator's true_final_state (ground truth), basis=SIMULATED — same
    method experiments/revenue_protection/run.py already uses, just live
    and per-batch inside the running app instead of an offline script.
  - RAZORPAY_TEST payments: a real Test Mode order is created via the
    Razorpay SDK as the concrete recovery action (a fresh payment link
    for the customer to complete), basis=ESTIMATED until/unless a later
    webhook confirms it — never claimed as VERIFIED money recovered
    unless it genuinely is.
  - Everything else (e.g. USER_UPLOAD with no ground truth): the action
    is still executed and logged, but recovered_value is left null with
    basis=PREDICTED — never fabricated.
"""
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from .models.db import AuditLog, Payment, RecoveryAction

# ---------------------------------------------------------------------------
# Bounded-workflow guardrails — the "stopping rules" and "compliant
# escalation" the spec asks for. Deliberately conservative defaults; all
# are overridable per-call (e.g. from query params) but never unboundable.
# ---------------------------------------------------------------------------
MAX_ATTEMPTS_PER_PAYMENT = 2
DEFAULT_BATCH_EXPOSURE_CAP = 500_000.0       # ₹5L per batch run, ceiling on auto-action
DEFAULT_ESCALATE_VALUE_THRESHOLD = 5_000.0   # txn above this never auto-executes
DEFAULT_ESCALATE_CONFIDENCE_FLOOR = 0.55     # model confidence below this never auto-executes


@dataclass
class BatchSummary:
    batch_id: str
    candidates_considered: int = 0
    executed: int = 0
    escalated: int = 0
    blocked_stopping_rule: int = 0
    skipped_batch_cap: int = 0
    total_txn_value_considered: float = 0.0
    measured_recovered_value: float = 0.0
    escalated_value: float = 0.0
    actions: list = field(default_factory=list)


def _latest_recommendation_per_payment(db: Session):
    """One row per payment_id: the most recent AuditLog entry, joined to
    the payment. Only payments whose latest recommendation is RECOVER are
    candidates — a payment that has since moved to WAIT/VERIFY/STOP on a
    fresher observation is correctly excluded."""
    latest_ts = (
        db.query(AuditLog.entity_id, func.max(AuditLog.timestamp).label("ts"))
        .filter(AuditLog.entity_type == "payment")
        .group_by(AuditLog.entity_id)
        .subquery()
    )
    rows = (
        db.query(AuditLog, Payment)
        .join(latest_ts, (AuditLog.entity_id == latest_ts.c.entity_id) & (AuditLog.timestamp == latest_ts.c.ts))
        .join(Payment, AuditLog.entity_id == Payment.payment_id)
        .filter(AuditLog.entity_type == "payment", AuditLog.recommendation == "RECOVER")
        .all()
    )
    return rows


def _prior_attempts(db: Session, payment_id: str) -> int:
    return db.query(RecoveryAction).filter(RecoveryAction.payment_id == payment_id).count()


def _already_resolved(db: Session, payment_id: str) -> bool:
    """A payment is done with this engine once it has an EXECUTED or
    ESCALATED action — this is the idempotency guardrail: recovery is
    attempted once (or escalated once), never repeatedly."""
    return (
        db.query(RecoveryAction)
        .filter(RecoveryAction.payment_id == payment_id,
                RecoveryAction.status.in_(["EXECUTED", "ESCALATED"]))
        .count() > 0
    )


def _execute_synthetic(payment: Payment) -> tuple[str, float | None, str]:
    """SYNTHETIC/USER_UPLOAD payments: no real gateway to call, so the
    'action' is the same conceptual retry experiments/revenue_protection
    measures — and it is scored the same honest way: recovered_value only
    counts when the simulator's ground truth says the payment was truly
    failed and worth fighting for; basis is always SIMULATED, never
    dressed up as verified production money."""
    if payment.true_final_state == "FAILED":
        return "RETRY_SIMULATED", round(payment.amount, 2), "SIMULATED"
    if payment.true_final_state is None:
        return "RETRY_SIMULATED", None, "PREDICTED"
    # Ground truth shows the payment actually succeeded — retrying it would
    # have been an unnecessary/duplicate action. Logged honestly as such.
    return "RETRY_SIMULATED", 0.0, "SIMULATED"


def _execute_razorpay(payment: Payment) -> tuple[str, float | None, str]:
    """RAZORPAY_TEST payments: create a real Test Mode order as the
    concrete recovery action (a fresh payment link). Never claims the
    money as recovered here — that only happens once a webhook later
    confirms payment.captured for the new order (VERIFIED elsewhere)."""
    from .razorpay_client import RazorpayNotConfiguredError, create_test_order
    try:
        create_test_order(amount_paise=int(round(payment.amount * 100)),
                           receipt=f"recovery-{payment.payment_id}")
        return "RETRY_LINK_CREATED", None, "ESTIMATED"
    except RazorpayNotConfiguredError:
        return "RETRY_LINK_SKIPPED_NOT_CONFIGURED", None, "ESTIMATED"
    except Exception:
        # Same boundary-to-external-service reasoning as routers/razorpay.py —
        # a failed outbound call must never crash the batch; log and move on.
        return "RETRY_LINK_FAILED", None, "ESTIMATED"


def run_recovery_batch(
    db: Session,
    limit: int = 100,
    batch_exposure_cap: float = DEFAULT_BATCH_EXPOSURE_CAP,
    escalate_value_threshold: float = DEFAULT_ESCALATE_VALUE_THRESHOLD,
    escalate_confidence_floor: float = DEFAULT_ESCALATE_CONFIDENCE_FLOOR,
) -> BatchSummary:
    batch_id = f"batch_{uuid.uuid4().hex[:12]}"
    summary = BatchSummary(batch_id=batch_id)

    candidates = _latest_recommendation_per_payment(db)
    # Deterministic ordering: highest transaction value first, so the
    # batch-exposure cap (a stopping rule) protects the highest-value
    # payments' chance of being acted on, not an arbitrary DB order.
    candidates.sort(key=lambda ap: ap[1].amount or 0, reverse=True)
    candidates = candidates[:limit]
    summary.candidates_considered = len(candidates)

    committed_value = 0.0

    for audit, payment in candidates:
        txn_value = float(payment.amount or 0)
        confidence = float(audit.confidence or 0.0)
        summary.total_txn_value_considered += txn_value

        if _already_resolved(db, payment.payment_id):
            continue  # idempotency guardrail — silently skip, not an error

        attempts_so_far = _prior_attempts(db, payment.payment_id)
        action_id = f"ra_{uuid.uuid4().hex[:12]}"
        now = datetime.now(timezone.utc)

        # --- Guardrail 1: retry cap (stopping rule) ---
        if attempts_so_far >= MAX_ATTEMPTS_PER_PAYMENT:
            row = RecoveryAction(
                action_id=action_id, batch_id=batch_id, payment_id=payment.payment_id,
                attempt_number=attempts_so_far + 1, decision=audit.recommendation,
                status="BLOCKED_STOPPING_RULE", action_type=None,
                reason=f"payment already has {attempts_so_far} prior recovery attempts "
                       f"(cap is {MAX_ATTEMPTS_PER_PAYMENT}) — stopping rule engaged",
                txn_value=txn_value, recovered_value=None, financial_basis=None,
                created_at=now,
            )
            db.add(row)
            summary.blocked_stopping_rule += 1
            summary.actions.append(_serialize(row))
            continue

        # --- Guardrail 2: batch exposure cap (stopping rule) ---
        if committed_value + txn_value > batch_exposure_cap:
            row = RecoveryAction(
                action_id=action_id, batch_id=batch_id, payment_id=payment.payment_id,
                attempt_number=attempts_so_far + 1, decision=audit.recommendation,
                status="SKIPPED_BATCH_CAP", action_type=None,
                reason=f"batch exposure cap of ₹{batch_exposure_cap:,.0f} reached — "
                       f"left for a future run rather than acting on everything at once",
                txn_value=txn_value, recovered_value=None, financial_basis=None,
                created_at=now,
            )
            db.add(row)
            summary.skipped_batch_cap += 1
            summary.actions.append(_serialize(row))
            continue

        # --- Guardrail 3: compliant escalation (never auto-act on high-value
        # or low-confidence cases; route to human/merchant review instead) ---
        if txn_value >= escalate_value_threshold or confidence < escalate_confidence_floor:
            reason_bits = []
            if txn_value >= escalate_value_threshold:
                reason_bits.append(f"transaction value ₹{txn_value:,.0f} >= auto-recovery "
                                    f"threshold ₹{escalate_value_threshold:,.0f}")
            if confidence < escalate_confidence_floor:
                reason_bits.append(f"model confidence {confidence:.2f} below auto-execute "
                                    f"floor {escalate_confidence_floor:.2f}")
            row = RecoveryAction(
                action_id=action_id, batch_id=batch_id, payment_id=payment.payment_id,
                attempt_number=attempts_so_far + 1, decision=audit.recommendation,
                status="ESCALATED", action_type="ESCALATE_TO_MERCHANT",
                reason="routed to merchant/compliance review — " + "; ".join(reason_bits),
                txn_value=txn_value, recovered_value=None, financial_basis=None,
                created_at=now, executed_at=now,
            )
            db.add(row)
            summary.escalated += 1
            summary.escalated_value += txn_value
            summary.actions.append(_serialize(row))
            committed_value += txn_value
            continue

        # --- Execute ---
        if payment.source == "RAZORPAY_TEST":
            action_type, recovered_value, basis = _execute_razorpay(payment)
        else:
            action_type, recovered_value, basis = _execute_synthetic(payment)

        row = RecoveryAction(
            action_id=action_id, batch_id=batch_id, payment_id=payment.payment_id,
            attempt_number=attempts_so_far + 1, decision=audit.recommendation,
            status="EXECUTED", action_type=action_type,
            reason="auto-executed within bounds (value and confidence both cleared "
                   "escalation thresholds)",
            txn_value=txn_value, recovered_value=recovered_value, financial_basis=basis,
            created_at=now, executed_at=now,
        )
        db.add(row)
        summary.executed += 1
        if recovered_value:
            summary.measured_recovered_value += recovered_value
        summary.actions.append(_serialize(row))
        committed_value += txn_value

        # Recovery actions are themselves audit-logged like every other
        # decision in this app (section 35/66's searchable audit trail
        # covers this engine too, not just predictions).
        db.add(AuditLog(
            entity_type="recovery_action", entity_id=payment.payment_id,
            recommendation=audit.recommendation, confidence=confidence,
            evidence_json={"action_type": action_type, "batch_id": batch_id},
            expected_impact=recovered_value,
        ))

    db.commit()
    summary.measured_recovered_value = round(summary.measured_recovered_value, 2)
    summary.escalated_value = round(summary.escalated_value, 2)
    summary.total_txn_value_considered = round(summary.total_txn_value_considered, 2)
    return summary


def _serialize(row: RecoveryAction) -> dict:
    return {
        "action_id": row.action_id, "payment_id": row.payment_id, "status": row.status,
        "action_type": row.action_type, "reason": row.reason, "txn_value": row.txn_value,
        "recovered_value": row.recovered_value, "financial_basis": row.financial_basis,
    }
