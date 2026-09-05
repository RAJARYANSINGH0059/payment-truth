"""SQLAlchemy models — Section 36/67. SQLite locally, Postgres in deployment
(same models, DATABASE_URL decides the engine — see app/db.py)."""
from datetime import datetime, timezone

from sqlalchemy import (Boolean, Column, DateTime, Float, ForeignKey, Integer,
                         JSON, String, Text)
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()


def utcnow() -> datetime:
    """Timezone-aware replacement for the deprecated datetime.utcnow().
    Passed as a Column `default=` callable (no parens) throughout this file."""
    return datetime.now(timezone.utc)



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
    source = Column(String)  # SYNTHETIC / RAZORPAY_TEST
    observed_status = Column(String, default="UNKNOWN")
    true_final_state = Column(String, nullable=True)  # only ever known post-hoc / in sim
    resolved_at = Column(DateTime, nullable=True)

    events = relationship("PaymentEvent", back_populates="payment")
    predictions = relationship("Prediction", back_populates="payment")


class PaymentEvent(Base):
    __tablename__ = "payment_events"
    event_id = Column(String, primary_key=True)
    payment_id = Column(String, ForeignKey("payments.payment_id"), index=True)
    event_type = Column(String)
    event_time = Column(DateTime, nullable=True)   # true time, if known (e.g. simulation)
    received_time = Column(DateTime, default=utcnow)
    razorpay_event_id = Column(String, nullable=True, unique=False, index=True)
    duplicate_flag = Column(Boolean, default=False)
    out_of_order_flag = Column(Boolean, default=False)
    raw_payload = Column(JSON, nullable=True)
    source = Column(String)

    payment = relationship("Payment", back_populates="events")


class ObservationSnapshot(Base):
    __tablename__ = "observation_snapshots"
    id = Column(Integer, primary_key=True, autoincrement=True)
    payment_id = Column(String, ForeignKey("payments.payment_id"), index=True)
    observation_at = Column(DateTime)
    observed_status_at_snapshot = Column(String)
    features_json = Column(JSON)
    source = Column(String)


class Prediction(Base):
    __tablename__ = "predictions"
    id = Column(Integer, primary_key=True, autoincrement=True)
    payment_id = Column(String, ForeignKey("payments.payment_id"), index=True)
    predicted_at = Column(DateTime, default=utcnow)
    p_success = Column(Float)
    p_pending = Column(Float)
    p_failed = Column(Float)
    confidence = Column(Float)
    model_version = Column(String)
    top_features_json = Column(JSON, nullable=True)
    actual_outcome = Column(String, nullable=True)   # filled in once resolved
    was_correct = Column(Boolean, nullable=True)

    payment = relationship("Payment", back_populates="predictions")


class Incident(Base):
    __tablename__ = "incidents"
    incident_id = Column(String, primary_key=True)
    detected_at = Column(DateTime, default=utcnow)
    severity = Column(String)  # LOW / MEDIUM / HIGH
    anomaly_score = Column(Float, nullable=True)
    affected_bank = Column(String, nullable=True)
    affected_method = Column(String, nullable=True)
    affected_merchant = Column(String, nullable=True)
    root_cause = Column(String, nullable=True)
    root_cause_confidence = Column(Float, nullable=True)
    supporting_evidence_json = Column(JSON, nullable=True)
    contradicting_evidence_json = Column(JSON, nullable=True)
    revenue_exposure = Column(Float, nullable=True)
    expected_recoverable_value = Column(Float, nullable=True)
    financial_basis = Column(String, nullable=True)  # VERIFIED/ESTIMATED/PREDICTED/SIMULATED
    resolved_at = Column(DateTime, nullable=True)
    outcome = Column(Text, nullable=True)


class Recommendation(Base):
    __tablename__ = "recommendations"
    id = Column(Integer, primary_key=True, autoincrement=True)
    payment_id = Column(String, ForeignKey("payments.payment_id"), nullable=True, index=True)
    incident_id = Column(String, ForeignKey("incidents.incident_id"), nullable=True, index=True)
    decision = Column(String)  # WAIT / VERIFY / RECOVER / STOP
    created_at = Column(DateTime, default=utcnow)
    rationale_json = Column(JSON, nullable=True)
    expected_impact = Column(Float, nullable=True)
    actual_outcome = Column(String, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(DateTime, default=utcnow)
    entity_type = Column(String)  # payment / incident
    entity_id = Column(String, index=True)
    prediction_json = Column(JSON, nullable=True)
    confidence = Column(Float, nullable=True)
    evidence_json = Column(JSON, nullable=True)
    recommendation = Column(String, nullable=True)
    expected_impact = Column(Float, nullable=True)
    actual_outcome = Column(String, nullable=True)
    model_version = Column(String, nullable=True)


class IncidentMemory(Base):
    __tablename__ = "incident_memory"
    incident_id = Column(String, primary_key=True)
    pattern_json = Column(JSON)
    payment_method = Column(String, nullable=True)
    bank = Column(String, nullable=True)
    failure_rate = Column(Float, nullable=True)
    duration_minutes = Column(Float, nullable=True)
    root_cause = Column(String, nullable=True)
    recommended_action = Column(String, nullable=True)
    actual_outcome = Column(String, nullable=True)
    revenue_impact = Column(Float, nullable=True)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    version = Column(String, primary_key=True)
    trained_at = Column(DateTime, default=utcnow)
    metrics_json = Column(JSON, nullable=True)
    artifact_path = Column(String, nullable=True)


class Experiment(Base):
    __tablename__ = "experiments"
    experiment_id = Column(String, primary_key=True)
    dataset_version = Column(String, nullable=True)
    generator_version = Column(String, nullable=True)
    seed = Column(Integer, nullable=True)
    model_version = Column(String, nullable=True)
    feature_version = Column(String, nullable=True)
    hyperparameters_json = Column(JSON, nullable=True)
    metrics_json = Column(JSON, nullable=True)
    timestamp = Column(DateTime, default=utcnow)


class RecoveryAction(Base):
    """Bounded recovery-workflow execution log (Track 3 bar: 'measured money
    recovered across a batch, with compliant escalation, stopping rules,
    and an audit trail'). One row per attempted action on a payment —
    never a second EXECUTED/ESCALATED row for the same payment_id, which
    is what makes the workflow bounded rather than an open retry loop."""
    __tablename__ = "recovery_actions"
    action_id = Column(String, primary_key=True)
    batch_id = Column(String, index=True)
    payment_id = Column(String, ForeignKey("payments.payment_id"), index=True)
    attempt_number = Column(Integer, default=1)
    decision = Column(String)  # the decision engine's output that triggered this row (normally RECOVER)
    status = Column(String)  # EXECUTED / ESCALATED / BLOCKED_STOPPING_RULE / SKIPPED_BATCH_CAP
    action_type = Column(String, nullable=True)  # RETRY_SIMULATED / RETRY_LINK_CREATED / ESCALATE_TO_MERCHANT
    reason = Column(Text, nullable=True)
    txn_value = Column(Float, nullable=True)
    recovered_value = Column(Float, nullable=True)
    financial_basis = Column(String, nullable=True)  # VERIFIED / ESTIMATED / PREDICTED / SIMULATED
    created_at = Column(DateTime, default=utcnow)
    executed_at = Column(DateTime, nullable=True)


class DataSource(Base):
    __tablename__ = "data_sources"
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String)  # SYNTHETIC / RAZORPAY_TEST / USER_UPLOAD
    imported_at = Column(DateTime, default=utcnow)
    rows_imported = Column(Integer, default=0)
    rows_invalid = Column(Integer, default=0)
