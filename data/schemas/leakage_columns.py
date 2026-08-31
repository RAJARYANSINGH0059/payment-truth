"""
LEAKAGE_COLUMNS — Section 12 / Section 43 compliance.

Any column in this set may exist in the dataset for evaluation, debugging,
or provenance purposes, but MUST NEVER be passed into a model's feature
matrix. The feature-building code and the training pipeline both import
this list and assert against it before fitting anything.

If you add a new column anywhere in the pipeline that encodes the final
answer, a future event, or the simulation's internal truth, add it here.
"""

# Columns that directly reveal the final/eventual outcome of a payment.
FINAL_OUTCOME_COLUMNS = {
    "true_final_state",          # CAPTURED / FAILED / REFUNDED (ground truth)
    "final_observed_state",      # SUCCESS / FAILED (merchant-observed final)
    "resolved_at",
    "time_to_resolution_sec",
    "recommendation_outcome",    # whether the WAIT/VERIFY/RECOVER/STOP call was right
}

# Columns that only exist because we (the simulator) know the future.
FUTURE_INFORMATION_COLUMNS = {
    "future_events",
    "next_event_type",
    "next_event_time",
    "events_after_observation",
}

# Columns that identify *why* something happened in the simulation, which a
# real merchant system would never have access to at prediction time.
GROUND_TRUTH_CAUSE_COLUMNS = {
    "incident_id",
    "incident_cause",            # BANK_DEGRADATION / WEBHOOK_PROCESSING / ...
    "scenario",                  # e.g. "late_capture", "hard_negative"
    "is_hard_negative",
}

# Columns that exist purely for reproducibility/provenance and would leak
# the simulation's internal state if used as a predictive feature.
PROVENANCE_COLUMNS = {
    "seed",
    "generator_version",
    "simulation_config_hash",
    "dataset_version",
}

LEAKAGE_COLUMNS = (
    FINAL_OUTCOME_COLUMNS
    | FUTURE_INFORMATION_COLUMNS
    | GROUND_TRUTH_CAUSE_COLUMNS
    | PROVENANCE_COLUMNS
)


def assert_no_leakage(feature_columns):
    """Raise loudly if any forbidden column made it into a feature matrix.

    Call this immediately before fitting or predicting with any model.
    """
    offending = LEAKAGE_COLUMNS.intersection(set(feature_columns))
    if offending:
        raise ValueError(
            "DATA LEAKAGE DETECTED — the following columns are forbidden "
            f"as model features: {sorted(offending)}. These columns encode "
            "final outcome, future information, ground-truth cause, or "
            "simulation provenance and must be excluded before training "
            "or inference. See data/schemas/leakage_columns.py."
        )
