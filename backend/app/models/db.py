"""
SQLAlchemy models — Payment Truth.

SQLite locally, Postgres in deployment.
The DATABASE_URL decides the engine — see app/db.py.
"""

from datetime import datetime, timezone

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    JSON,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base, relationship


Base = declarative_base()


def utcnow() -> datetime:
    """
    Timezone-aware replacement for datetime.utcnow().

    Used as a Column default callable throughout this file.
    """
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------------
# PAYMENTS
# ---------------------------------------------------------------------------

class Payment(Base):
    __tablename__ = "payments"

    payment_id = Column(String, primary_key=True)

    order_id = Column(String, index=True)
    customer_id = Column(String, index=True)
    merchant_id = Column(String, index=True)

    amount = Column(Float)
    currency = Column(String, default="INR")

    payment_method = Column(String)
    bank = Column(String, nullable=True)

    created_at = Column(DateTime, default=utcnow)

    # SYNTHETIC / RAZORPAY_TEST
    source = Column(String)

    observed_status = Column(String, default="UNKNOWN")

    # Only known post-hoc / in simulation
    true_final_state = Column(String, nullable=True)

    resolved_at = Column(DateTime, nullable=True)

    events = relationship(
        "PaymentEvent",
        back_populates="payment",
    )

    predictions = relationship(
        "Prediction",
        back_populates="payment",
    )


# ---------------------------------------------------------------------------
# PAYMENT EVENTS
# ---------------------------------------------------------------------------

class PaymentEvent(Base):
    __tablename__ = "payment_events"

    event_id = Column(String, primary_key=True)

    payment_id = Column(
        String,
        ForeignKey("payments.payment_id"),
        index=True,
    )

    event_type = Column(String)

    # True event time, when known
    event_time = Column(DateTime, nullable=True)

    received_time = Column(
        DateTime,
        default=utcnow,
    )

    razorpay_event_id = Column(
        String,
        nullable=True,
        unique=False,
        index=True,
    )

    duplicate_flag = Column(
        Boolean,
        default=False,
    )

    out_of_order_flag = Column(
        Boolean,
        default=False,
    )

    raw_payload = Column(
        JSON,
        nullable=True,
    )

    source = Column(String)

    payment = relationship(
        "Payment",
        back_populates="events",
    )


# ---------------------------------------------------------------------------
# OBSERVATION SNAPSHOTS
# ---------------------------------------------------------------------------

class ObservationSnapshot(Base):
    __tablename__ = "observation_snapshots"

    id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    payment_id = Column(
        String,
        ForeignKey("payments.payment_id"),
        index=True,
    )

    observation_at = Column(DateTime)

    observed_status_at_snapshot = Column(String)

    features_json = Column(JSON)

    source = Column(String)


# ---------------------------------------------------------------------------
# PREDICTIONS
# ---------------------------------------------------------------------------

class Prediction(Base):
    __tablename__ = "predictions"

    id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    payment_id = Column(
        String,
        ForeignKey("payments.payment_id"),
        index=True,
    )

    predicted_at = Column(
        DateTime,
        default=utcnow,
    )

    p_success = Column(Float)
    p_pending = Column(Float)
    p_failed = Column(Float)

    confidence = Column(Float)

    model_version = Column(String)

    top_features_json = Column(
        JSON,
        nullable=True,
    )

    # Filled once the payment is resolved
    actual_outcome = Column(
        String,
        nullable=True,
    )

    was_correct = Column(
        Boolean,
        nullable=True,
    )

    payment = relationship(
        "Payment",
        back_populates="predictions",
    )


# ---------------------------------------------------------------------------
# INCIDENTS
# ---------------------------------------------------------------------------

class Incident(Base):
    __tablename__ = "incidents"

    incident_id = Column(
        String,
        primary_key=True,
    )

    detected_at = Column(
        DateTime,
        default=utcnow,
    )

    # LOW / MEDIUM / HIGH
    severity = Column(String)

    anomaly_score = Column(
        Float,
        nullable=True,
    )

    affected_bank = Column(
        String,
        nullable=True,
    )

    affected_method = Column(
        String,
        nullable=True,
    )

    affected_merchant = Column(
        String,
        nullable=True,
    )

    root_cause = Column(
        String,
        nullable=True,
    )

    root_cause_confidence = Column(
        Float,
        nullable=True,
    )

    supporting_evidence_json = Column(
        JSON,
        nullable=True,
    )

    contradicting_evidence_json = Column(
        JSON,
        nullable=True,
    )

    revenue_exposure = Column(
        Float,
        nullable=True,
    )

    expected_recoverable_value = Column(
        Float,
        nullable=True,
    )

    # VERIFIED / ESTIMATED / PREDICTED / SIMULATED
    financial_basis = Column(
        String,
        nullable=True,
    )

    resolved_at = Column(
        DateTime,
        nullable=True,
    )

    outcome = Column(
        Text,
        nullable=True,
    )


# ---------------------------------------------------------------------------
# RECOMMENDATIONS
# ---------------------------------------------------------------------------

class Recommendation(Base):
    __tablename__ = "recommendations"

    id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    payment_id = Column(
        String,
        ForeignKey("payments.payment_id"),
        nullable=True,
        index=True,
    )

    incident_id = Column(
        String,
        ForeignKey("incidents.incident_id"),
        nullable=True,
        index=True,
    )

    # WAIT / VERIFY / RECOVER / STOP
    decision = Column(String)

    created_at = Column(
        DateTime,
        default=utcnow,
    )

    rationale_json = Column(
        JSON,
        nullable=True,
    )

    expected_impact = Column(
        Float,
        nullable=True,
    )

    actual_outcome = Column(
        String,
        nullable=True,
    )


# ---------------------------------------------------------------------------
# AUDIT LOG
# ---------------------------------------------------------------------------

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    timestamp = Column(
        DateTime,
        default=utcnow,
    )

    # payment / incident / recovery_action
    entity_type = Column(String)

    entity_id = Column(
        String,
        index=True,
    )

    prediction_json = Column(
        JSON,
        nullable=True,
    )

    confidence = Column(
        Float,
        nullable=True,
    )

    evidence_json = Column(
        JSON,
        nullable=True,
    )

    recommendation = Column(
        String,
        nullable=True,
    )

    expected_impact = Column(
        Float,
        nullable=True,
    )

    actual_outcome = Column(
        String,
        nullable=True,
    )

    model_version = Column(
        String,
        nullable=True,
    )


# ---------------------------------------------------------------------------
# INCIDENT MEMORY
# ---------------------------------------------------------------------------

class IncidentMemory(Base):
    __tablename__ = "incident_memory"

    incident_id = Column(
        String,
        primary_key=True,
    )

    pattern_json = Column(JSON)

    payment_method = Column(
        String,
        nullable=True,
    )

    bank = Column(
        String,
        nullable=True,
    )

    failure_rate = Column(
        Float,
        nullable=True,
    )

    duration_minutes = Column(
        Float,
        nullable=True,
    )

    root_cause = Column(
        String,
        nullable=True,
    )

    recommended_action = Column(
        String,
        nullable=True,
    )

    actual_outcome = Column(
        String,
        nullable=True,
    )

    revenue_impact = Column(
        Float,
        nullable=True,
    )


# ---------------------------------------------------------------------------
# MODEL VERSIONS
# ---------------------------------------------------------------------------

class ModelVersion(Base):
    __tablename__ = "model_versions"

    version = Column(
        String,
        primary_key=True,
    )

    trained_at = Column(
        DateTime,
        default=utcnow,
    )

    metrics_json = Column(
        JSON,
        nullable=True,
    )

    artifact_path = Column(
        String,
        nullable=True,
    )


# ---------------------------------------------------------------------------
# EXPERIMENTS
# ---------------------------------------------------------------------------

class Experiment(Base):
    __tablename__ = "experiments"

    experiment_id = Column(
        String,
        primary_key=True,
    )

    dataset_version = Column(
        String,
        nullable=True,
    )

    generator_version = Column(
        String,
        nullable=True,
    )

    seed = Column(
        Integer,
        nullable=True,
    )

    model_version = Column(
        String,
        nullable=True,
    )

    feature_version = Column(
        String,
        nullable=True,
    )

    hyperparameters_json = Column(
        JSON,
        nullable=True,
    )

    metrics_json = Column(
        JSON,
        nullable=True,
    )

    timestamp = Column(
        DateTime,
        default=utcnow,
    )


# ---------------------------------------------------------------------------
# DATA SOURCES
# ---------------------------------------------------------------------------

class DataSource(Base):
    __tablename__ = "data_sources"

    id = Column(
        Integer,
        primary_key=True,
        autoincrement=True,
    )

    # SYNTHETIC / RAZORPAY_TEST / USER_UPLOAD
    name = Column(String)

    imported_at = Column(
        DateTime,
        default=utcnow,
    )

    rows_imported = Column(
        Integer,
        default=0,
    )

    rows_invalid = Column(
        Integer,
        default=0,
    )


# ---------------------------------------------------------------------------
# RECOVERY ACTIONS
# ---------------------------------------------------------------------------
#
# This model is required by:
#
#   backend/app/recovery_engine.py
#   backend/app/routers/recovery.py
#
# The recovery engine uses these fields for:
#   - idempotency
#   - retry caps
#   - batch exposure caps
#   - escalation
#   - recovery measurement
#   - audit trail
#
# Status values currently used by recovery_engine.py:
#
#   EXECUTED
#   ESCALATED
#   BLOCKED_STOPPING_RULE
#   SKIPPED_BATCH_CAP
#
# ---------------------------------------------------------------------------

class RecoveryAction(Base):
    __tablename__ = "recovery_actions"

    # Unique identifier for this recovery action
    action_id = Column(
        String,
        primary_key=True,
    )

    # Identifier of the recovery batch that created this action
    batch_id = Column(
        String,
        index=True,
    )

    # Payment being acted upon
    payment_id = Column(
        String,
        ForeignKey("payments.payment_id"),
        index=True,
    )

    # Number of recovery attempts for this payment
    attempt_number = Column(
        Integer,
        default=1,
    )

    # Original decision that caused the recovery workflow
    # e.g. RECOVER
    decision = Column(String)

    # EXECUTED / ESCALATED /
    # BLOCKED_STOPPING_RULE / SKIPPED_BATCH_CAP
    status = Column(
        String,
        index=True,
    )

    # Examples:
    # RETRY_SIMULATED
    # RETRY_LINK_CREATED
    # RETRY_LINK_SKIPPED_NOT_CONFIGURED
    # RETRY_LINK_FAILED
    # ESCALATE_TO_MERCHANT
    action_type = Column(
        String,
        nullable=True,
    )

    # Human-readable explanation for the action
    reason = Column(
        Text,
        nullable=True,
    )

    # Transaction amount considered for this action
    txn_value = Column(
        Float,
        nullable=True,
    )

    # Amount actually measured as recovered.
    # Can be NULL when recovery has not been verified/measured.
    recovered_value = Column(
        Float,
        nullable=True,
    )

    # VERIFIED / ESTIMATED / PREDICTED / SIMULATED
    financial_basis = Column(
        String,
        nullable=True,
    )

    # When the recovery action was created
    created_at = Column(
        DateTime,
        default=utcnow,
    )

    # When the action was actually executed
    executed_at = Column(
        DateTime,
        nullable=True,
    )
