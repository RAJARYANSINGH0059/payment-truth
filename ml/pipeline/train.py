#!/usr/bin/env python3
"""
Payment Truth — Phase 2/3/4 training pipeline.

Loads observation_snapshots.csv (the per-snapshot partial-information rows
built by data/generators/generate_dataset.py), builds a leakage-safe
feature matrix, splits by payment_id (never mixing one payment's snapshots
across train/val/test — section 19/33), trains baselines + XGBoost with
probability calibration, runs SHAP, and writes a full metrics report plus
model artifacts (section 47/48).

Usage:
    python ml/pipeline/train.py --data data/demo --out ml/artifacts
"""
import argparse
import json
import os
import sys
from collections import defaultdict

import joblib
import numpy as np
import pandas as pd
from sklearn.calibration import CalibratedClassifierCV
from sklearn.dummy import DummyClassifier
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (brier_score_loss, classification_report,
                              confusion_matrix, f1_score)
from sklearn.preprocessing import LabelEncoder, OneHotEncoder
import xgboost as xgb

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
from data.schemas.leakage_columns import LEAKAGE_COLUMNS, assert_no_leakage  # noqa: E402

CATEGORICAL = ["payment_method", "bank", "merchant_type", "observed_status_at_snapshot"]
NUMERIC = ["amount", "hour_of_day", "day_of_week", "previous_payment_count",
           "previous_success_rate", "event_count", "duplicate_event_count",
           "time_since_payment_sec", "time_since_last_event_sec"]
BOOL = ["event_order_anomaly"]
IDENTIFIER_COLS = ["payment_id", "observation_at", "source"]
TARGET = "final_observed_state"  # SUCCESS / FAILED (PENDING reserved for
                                  # payments that never resolve within the
                                  # sim window — none in Phase-1 data yet;
                                  # documented simplification, see README)


def load(data_dir):
    payments = pd.read_csv(os.path.join(data_dir, "payments.csv"))
    snaps = pd.read_csv(os.path.join(data_dir, "observation_snapshots.csv"))
    return payments, snaps


def build_features(snaps: pd.DataFrame):
    df = snaps.copy()
    feature_cols = CATEGORICAL + NUMERIC + BOOL
    assert_no_leakage(feature_cols)  # hard gate — section 12/45

    encoders = {}
    X_parts = []
    for col in CATEGORICAL:
        le = LabelEncoder()
        X_parts.append(pd.Series(le.fit_transform(df[col].astype(str)), name=col))
        encoders[col] = {c: int(i) for i, c in enumerate(le.classes_)}
    for col in NUMERIC:
        X_parts.append(df[col].astype(float))
    for col in BOOL:
        X_parts.append(df[col].astype(int))
    X = pd.concat(X_parts, axis=1)
    y = df[TARGET]
    return X, y, encoders, feature_cols


def split_by_payment(df: pd.DataFrame, seed=42):
    """Section 19: split by payment_id so no payment's snapshots leak across
    train/val/test."""
    pids = np.array(df["payment_id"].unique(), dtype=object)
    rng = np.random.RandomState(seed)
    rng.shuffle(pids)
    n = len(pids)
    train_ids = set(pids[: int(n * 0.7)])
    val_ids = set(pids[int(n * 0.7): int(n * 0.85)])
    test_ids = set(pids[int(n * 0.85):])
    return train_ids, val_ids, test_ids


def time_based_split(payments: pd.DataFrame, snaps: pd.DataFrame):
    """Section 33: separate time-based holdout — payments created in the
    final ~15% of the simulated period become the time-holdout test set."""
    payments = payments.copy()
    payments["created_at"] = pd.to_datetime(payments["created_at"])
    cutoff = payments["created_at"].quantile(0.85)
    late_ids = set(payments[payments["created_at"] > cutoff]["payment_id"])
    early_ids = set(payments[payments["created_at"] <= cutoff]["payment_id"])
    return early_ids, late_ids


def evaluate(name, y_true, y_pred, y_proba, classes):
    report = classification_report(y_true, y_pred, output_dict=True, zero_division=0)
    cm = confusion_matrix(y_true, y_pred, labels=classes).tolist()
    result = {
        "name": name,
        "n": int(len(y_true)),
        "macro_f1": round(f1_score(y_true, y_pred, average="macro", zero_division=0), 4),
        "per_class": {k: {kk: round(vv, 4) for kk, vv in v.items()}
                      for k, v in report.items() if k in classes},
        "confusion_matrix": {"labels": classes, "matrix": cm},
    }
    if y_proba is not None and "SUCCESS" in classes:
        idx = classes.index("SUCCESS")
        binary_true = (y_true == "SUCCESS").astype(int)
        result["brier_score_success"] = round(brier_score_loss(binary_true, y_proba[:, idx]), 4)
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="data/demo")
    ap.add_argument("--out", default="ml/artifacts")
    args = ap.parse_args()

    payments, snaps = load(args.data)
    os.makedirs(args.out, exist_ok=True)

    X, y, encoders, feature_cols = build_features(snaps)
    df = snaps  # aligned index with X, y

    train_ids, val_ids, test_ids = split_by_payment(df)
    early_ids, late_ids = time_based_split(payments, snaps)

    def mask(ids):
        return df["payment_id"].isin(ids).values

    tr, va, te = mask(train_ids), mask(val_ids), mask(test_ids)
    X_train, y_train = X[tr], y[tr]
    X_val, y_val = X[va], y[va]
    X_test, y_test = X[te], y[te]

    classes = sorted(y.unique().tolist())

    results = {"phase": "3-4", "feature_columns": feature_cols, "classes": classes,
               "n_train": int(tr.sum()), "n_val": int(va.sum()), "n_test": int(te.sum()),
               "models": {}}

    # ---- Baseline 1: majority class ----
    dummy = DummyClassifier(strategy="most_frequent").fit(X_train, y_train)
    y_pred = dummy.predict(X_test)
    results["models"]["majority_baseline"] = evaluate("majority_baseline", y_test.values, y_pred, None, classes)

    # ---- Baseline 2: rule-based (observed_status IS the prediction) ----
    rule_pred = df.loc[te, "observed_status_at_snapshot"].map(
        {"SUCCESS": "SUCCESS", "FAILED": "FAILED", "PENDING": "FAILED", "UNKNOWN": "FAILED"}
    ).values
    results["models"]["rule_based_baseline"] = evaluate("rule_based_baseline", y_test.values, rule_pred, None, classes)

    # ---- Baseline 3: Logistic Regression ----
    lr = LogisticRegression(max_iter=500).fit(X_train, y_train)
    y_pred = lr.predict(X_test)
    y_proba = lr.predict_proba(X_test)
    lr_classes = lr.classes_.tolist()
    results["models"]["logistic_regression"] = evaluate("logistic_regression", y_test.values, y_pred, y_proba, lr_classes)

    # ---- XGBoost (primary model) + calibration ----
    label_enc = LabelEncoder().fit(y_train)
    xgb_model = xgb.XGBClassifier(
        n_estimators=200, max_depth=4, learning_rate=0.08,
        subsample=0.85, colsample_bytree=0.85, eval_metric="mlogloss",
        random_state=42,
    )
    xgb_model.fit(X_train, label_enc.transform(y_train))
    xgb_classes = label_enc.classes_.tolist()

    # sklearn >=1.6 dropped cv="prefit"; cross-validated calibration on the
    # combined train+val split gives the same intent (calibrate probabilities
    # without calibrating on the final test set) without relying on a
    # version-specific API.
    calib_fit_mask = tr | va
    calibrated = CalibratedClassifierCV(
        xgb.XGBClassifier(n_estimators=200, max_depth=4, learning_rate=0.08,
                           subsample=0.85, colsample_bytree=0.85,
                           eval_metric="mlogloss", random_state=42),
        method="isotonic", cv=3,
    )
    calibrated.fit(X[calib_fit_mask], label_enc.transform(y[calib_fit_mask]))

    y_pred_idx = calibrated.predict(X_test)
    y_pred = label_enc.inverse_transform(y_pred_idx)
    y_proba = calibrated.predict_proba(X_test)
    results["models"]["xgboost_calibrated"] = evaluate("xgboost_calibrated", y_test.values, y_pred, y_proba, xgb_classes)

    # ---- Time-based holdout (section 33) ----
    time_test_mask = df["payment_id"].isin(late_ids).values & te
    if time_test_mask.sum() > 0:
        y_pred_time_idx = calibrated.predict(X[time_test_mask])
        y_pred_time = label_enc.inverse_transform(y_pred_time_idx)
        results["time_based_holdout"] = evaluate(
            "xgboost_calibrated_time_holdout", y[time_test_mask].values, y_pred_time,
            calibrated.predict_proba(X[time_test_mask]), xgb_classes)

    # ---- Unseen-incident evaluation (section 34) ----
    incident_test_mask = te & df["incident_id"].notna().values
    if incident_test_mask.sum() > 5:
        y_pred_inc_idx = calibrated.predict(X[incident_test_mask])
        y_pred_inc = label_enc.inverse_transform(y_pred_inc_idx)
        results["incident_touched_test_subset"] = evaluate(
            "xgboost_calibrated_incident_subset", df.loc[incident_test_mask, TARGET].values,
            y_pred_inc, calibrated.predict_proba(X[incident_test_mask]), xgb_classes)

    # ---- SHAP (section 42) ----
    try:
        import shap
        explainer = shap.TreeExplainer(xgb_model)
        shap_values = explainer.shap_values(X_test.iloc[:200])
        if isinstance(shap_values, list):
            mean_abs = np.mean([np.abs(sv).mean(axis=0) for sv in shap_values], axis=0)
        else:
            mean_abs = np.abs(shap_values).mean(axis=(0, 2)) if shap_values.ndim == 3 else np.abs(shap_values).mean(axis=0)
        importance = sorted(zip(feature_cols, mean_abs.tolist()), key=lambda x: -x[1])
        results["shap_top_features"] = [{"feature": f, "mean_abs_shap": round(v, 4)} for f, v in importance]
    except Exception as ex:
        results["shap_error"] = str(ex)

    # ---- Beats-baseline acceptance test (section 74) ----
    best_baseline_f1 = max(results["models"]["majority_baseline"]["macro_f1"],
                            results["models"]["rule_based_baseline"]["macro_f1"])
    xgb_f1 = results["models"]["xgboost_calibrated"]["macro_f1"]
    results["beats_baseline"] = xgb_f1 > best_baseline_f1
    results["best_baseline_macro_f1"] = best_baseline_f1
    results["xgboost_macro_f1"] = xgb_f1

    # ---- Save artifacts (section 47) ----
    joblib.dump(xgb_model, os.path.join(args.out, "payment_state_model.joblib"))
    joblib.dump(calibrated, os.path.join(args.out, "probability_calibrator.joblib"))
    joblib.dump(label_enc, os.path.join(args.out, "label_encoder.joblib"))
    with open(os.path.join(args.out, "feature_schema.json"), "w") as f:
        json.dump({"feature_columns": feature_cols, "categorical_encoders": encoders,
                    "target": TARGET, "classes": xgb_classes}, f, indent=2)
    with open(os.path.join(args.out, "metrics.json"), "w") as f:
        json.dump(results, f, indent=2)

    print(json.dumps({
        "n_train": results["n_train"], "n_val": results["n_val"], "n_test": results["n_test"],
        "majority_baseline_macro_f1": results["models"]["majority_baseline"]["macro_f1"],
        "rule_based_baseline_macro_f1": results["models"]["rule_based_baseline"]["macro_f1"],
        "logistic_regression_macro_f1": results["models"]["logistic_regression"]["macro_f1"],
        "xgboost_calibrated_macro_f1": results["models"]["xgboost_calibrated"]["macro_f1"],
        "beats_baseline": results["beats_baseline"],
        "xgboost_brier_success": results["models"]["xgboost_calibrated"].get("brier_score_success"),
        "time_holdout_macro_f1": results.get("time_based_holdout", {}).get("macro_f1"),
        "incident_subset_macro_f1": results.get("incident_touched_test_subset", {}).get("macro_f1"),
        "top_shap_features": [x["feature"] for x in results.get("shap_top_features", [])[:5]],
    }, indent=2))


if __name__ == "__main__":
    main()
