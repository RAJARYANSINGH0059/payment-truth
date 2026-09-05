"""Recovery workflow — the ACT step. Executes bounded, auditable recovery
actions on payments the decision engine has already labelled RECOVER (see
recovery_engine.py for the stopping rules and escalation thresholds)."""
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from ..db import get_db
from ..models.db import RecoveryAction
from ..recovery_engine import (
    DEFAULT_BATCH_EXPOSURE_CAP,
    DEFAULT_ESCALATE_CONFIDENCE_FLOOR,
    DEFAULT_ESCALATE_VALUE_THRESHOLD,
    run_recovery_batch,
)

router = APIRouter(prefix="/api")


@router.post("/recovery/run")
def recovery_run(
    limit: int = 100,
    batch_exposure_cap: float = DEFAULT_BATCH_EXPOSURE_CAP,
    escalate_value_threshold: float = DEFAULT_ESCALATE_VALUE_THRESHOLD,
    escalate_confidence_floor: float = DEFAULT_ESCALATE_CONFIDENCE_FLOOR,
    db: Session = Depends(get_db),
):
    """Runs one bounded recovery batch: every payment currently labelled
    RECOVER is either executed, escalated for compliant human review, or
    blocked by a stopping rule (retry cap / batch exposure cap) — never an
    open-ended action. Returns the measured recovered value for this batch
    plus a full breakdown, so this can be called on demand or on a
    schedule."""
    summary = run_recovery_batch(
        db, limit=limit, batch_exposure_cap=batch_exposure_cap,
        escalate_value_threshold=escalate_value_threshold,
        escalate_confidence_floor=escalate_confidence_floor,
    )
    return {
        "batch_id": summary.batch_id,
        "candidates_considered": summary.candidates_considered,
        "executed": summary.executed,
        "escalated": summary.escalated,
        "blocked_stopping_rule": summary.blocked_stopping_rule,
        "skipped_batch_cap": summary.skipped_batch_cap,
        "total_txn_value_considered": summary.total_txn_value_considered,
        "measured_recovered_value": {"value": summary.measured_recovered_value, "basis": "SIMULATED/ESTIMATED — see per-action basis"},
        "escalated_value": summary.escalated_value,
        "actions": summary.actions,
    }


@router.get("/recovery/actions")
def list_recovery_actions(limit: int = 100, db: Session = Depends(get_db)):
    rows = db.query(RecoveryAction).order_by(RecoveryAction.created_at.desc()).limit(limit).all()
    return [{
        "action_id": r.action_id, "batch_id": r.batch_id, "payment_id": r.payment_id,
        "attempt_number": r.attempt_number, "decision": r.decision, "status": r.status,
        "action_type": r.action_type, "reason": r.reason, "txn_value": r.txn_value,
        "recovered_value": r.recovered_value, "financial_basis": r.financial_basis,
        "created_at": r.created_at.isoformat() if r.created_at else None,
        "executed_at": r.executed_at.isoformat() if r.executed_at else None,
    } for r in rows]


@router.get("/recovery/summary")
def recovery_summary(db: Session = Depends(get_db)):
    """All-time aggregates across every recovery batch ever run — feeds the
    Overview page's 'Revenue Recovered' figure."""
    rows = db.query(RecoveryAction).all()
    executed = [r for r in rows if r.status == "EXECUTED"]
    escalated = [r for r in rows if r.status == "ESCALATED"]
    blocked = [r for r in rows if r.status == "BLOCKED_STOPPING_RULE"]
    skipped = [r for r in rows if r.status == "SKIPPED_BATCH_CAP"]

    recovered_by_basis: dict = {}
    for r in executed:
        if r.recovered_value:
            recovered_by_basis[r.financial_basis] = recovered_by_basis.get(r.financial_basis, 0.0) + r.recovered_value

    return {
        "total_actions": len(rows),
        "executed": len(executed),
        "escalated": len(escalated),
        "blocked_stopping_rule": len(blocked),
        "skipped_batch_cap": len(skipped),
        "measured_recovered_value_by_basis": {k: round(v, 2) for k, v in recovered_by_basis.items()},
        "escalated_value_pending_review": round(sum(r.txn_value or 0 for r in escalated), 2),
    }
