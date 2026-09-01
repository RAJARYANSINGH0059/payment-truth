#!/usr/bin/env python3
"""
Unseen Incident Configuration experiment (completion-prompt sections 4-7).

TRAIN: generated with data/config/default.yaml
TEST:  generated with data/config/unseen_test.yaml — deliberately different
       severity/duration/failure-rate/traffic distributions, generated
       with a different seed, never touched during training.

Trains a fresh XGBoost model on TRAIN only, evaluates on TEST, and
compares against the same model's known-configuration performance (a
same-distribution holdout carved from TRAIN itself) to produce an honest
generalization gap — not a fabricated number.

Usage:
    python experiments/unseen_incident/run.py
"""
import json
import os
import subprocess
import sys

import joblib
import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.calibration import CalibratedClassifierCV
from sklearn.metrics import classification_report, confusion_matrix, f1_score
from sklearn.preprocessing import LabelEncoder

REPO_ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
sys.path.insert(0, REPO_ROOT)
from ml.pipeline.train import build_features, CATEGORICAL, NUMERIC, BOOL, TARGET  # noqa: E402

EXPERIMENT_DIR = os.path.dirname(__file__)
TRAIN_DIR = os.path.join(EXPERIMENT_DIR, "_train_data")
TEST_DIR = os.path.join(EXPERIMENT_DIR, "_test_data")


def generate(config_name: str, out_dir: str, seed: int, payments: int, sim_days: int):
    subprocess.run(
        [sys.executable, os.path.join(REPO_ROOT, "scripts", "generate_dataset.py"),
         "--payments", str(payments), "--seed", str(seed), "--sim-days", str(sim_days),
         "--config", config_name, "--out-dir", out_dir],
        check=True, capture_output=True, text=True,
    )


def score(y_true, y_pred, classes):
    return {
        "macro_f1": round(f1_score(y_true, y_pred, average="macro", zero_division=0), 4),
        "confusion_matrix": {"labels": classes, "matrix": confusion_matrix(y_true, y_pred, labels=classes).tolist()},
        "per_class": {k: v for k, v in classification_report(
            y_true, y_pred, output_dict=True, zero_division=0).items() if k in classes},
    }


def main():
    train_config = {"config": "default", "seed": 100, "payments": 6000, "sim_days": 4}
    test_config = {"config": "unseen_test", "seed": 999, "payments": 2000, "sim_days": 2}

    print("Generating TRAIN (default.yaml)...")
    generate(train_config["config"], TRAIN_DIR, train_config["seed"],
              train_config["payments"], train_config["sim_days"])
    print("Generating TEST (unseen_test.yaml — different distribution, never seen in training)...")
    generate(test_config["config"], TEST_DIR, test_config["seed"],
              test_config["payments"], test_config["sim_days"])

    train_snaps = pd.read_csv(os.path.join(TRAIN_DIR, "observation_snapshots.csv"))
    test_snaps = pd.read_csv(os.path.join(TEST_DIR, "observation_snapshots.csv"))

    X_train, y_train, encoders, feature_cols = build_features(train_snaps)
    X_test_raw = test_snaps.copy()

    # Encode TEST with TRAIN's fitted categorical mappings — unseen
    # categories map to 0 rather than crashing (a genuinely unseen bank
    # value, for instance, still needs to produce a prediction).
    X_test_parts = []
    for col in CATEGORICAL:
        mapping = encoders[col]
        X_test_parts.append(X_test_raw[col].astype(str).map(mapping).fillna(0).astype(int).rename(col))
    for col in NUMERIC:
        X_test_parts.append(X_test_raw[col].astype(float))
    for col in BOOL:
        X_test_parts.append(X_test_raw[col].astype(int))
    X_test = pd.concat(X_test_parts, axis=1)
    y_test = test_snaps[TARGET]

    # Known-configuration baseline: a same-distribution holdout carved
    # from TRAIN itself (last 15% by payment_id), so "known" and "unseen"
    # are compared on the same kind of split size, not apples to oranges.
    train_pids = np.array(train_snaps["payment_id"].unique(), dtype=object)
    rng = np.random.RandomState(42)
    rng.shuffle(train_pids)
    holdout_ids = set(train_pids[int(len(train_pids) * 0.85):])
    fit_ids = set(train_pids[:int(len(train_pids) * 0.85)])
    fit_mask = train_snaps["payment_id"].isin(fit_ids).values
    known_mask = train_snaps["payment_id"].isin(holdout_ids).values

    classes = sorted(set(y_train.unique()) | set(y_test.unique()))
    label_enc = LabelEncoder().fit(classes)

    model = xgb.XGBClassifier(n_estimators=200, max_depth=4, learning_rate=0.08,
                               subsample=0.85, colsample_bytree=0.85,
                               eval_metric="mlogloss", random_state=42)
    model.fit(X_train[fit_mask], label_enc.transform(y_train[fit_mask]))

    known_pred = label_enc.inverse_transform(model.predict(X_train[known_mask]))
    known_result = score(y_train[known_mask].values, known_pred, classes)

    unseen_pred = label_enc.inverse_transform(model.predict(X_test))
    unseen_result = score(y_test.values, unseen_pred, classes)

    generalization_gap = round(known_result["macro_f1"] - unseen_result["macro_f1"], 4)

    report = {
        "experiment": "unseen_incident_configuration",
        "train_config": train_config, "test_config": test_config,
        "n_train_fit": int(fit_mask.sum()), "n_known_holdout": int(known_mask.sum()),
        "n_unseen_test": len(y_test),
        "known_configuration": known_result,
        "unseen_configuration": unseen_result,
        "generalization_gap_macro_f1": generalization_gap,
        "note": ("Unseen config differs in incident severity/duration ranges, bank/method "
                 "baseline failure rates, and traffic density (see data/config/unseen_test.yaml). "
                 "Individual incidents still pick banks/methods at random within each config, "
                 "consistent with the generator's own anti-memorization design."),
    }

    with open(os.path.join(EXPERIMENT_DIR, "metrics.json"), "w") as f:
        json.dump(report, f, indent=2)
    with open(os.path.join(EXPERIMENT_DIR, "train_config.json"), "w") as f:
        json.dump(train_config, f, indent=2)
    with open(os.path.join(EXPERIMENT_DIR, "test_config.json"), "w") as f:
        json.dump(test_config, f, indent=2)

    print(json.dumps({
        "known_configuration_macro_f1": known_result["macro_f1"],
        "unseen_configuration_macro_f1": unseen_result["macro_f1"],
        "generalization_gap": generalization_gap,
    }, indent=2))


if __name__ == "__main__":
    main()
