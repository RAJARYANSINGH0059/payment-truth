"""
Loads ml/artifacts/* at startup and exposes predict_payment_state().
Also exposes reload_model(), called after auto-retraining (see
routers/simulation.py) so a freshly trained model is picked up without
restarting the process. If artifacts are missing (fresh clone, first run
before any training has happened yet), predict_payment_state() returns a
clearly-labeled fallback instead of crashing, so Simulation Mode still
runs end-to-end.
"""
import json
import os
import threading

import joblib
import pandas as pd

from .config import settings

_model = None
_calibrated = None
_label_enc = None
_schema = None
_load_error = None
_model_version = "none"
_lock = threading.Lock()


def _load():
    global _model, _calibrated, _label_enc, _schema, _load_error, _model_version
    d = settings.ML_ARTIFACTS_DIR
    try:
        model = joblib.load(os.path.join(d, "payment_state_model.joblib"))
        calibrated = joblib.load(os.path.join(d, "probability_calibrator.joblib"))
        label_enc = joblib.load(os.path.join(d, "label_encoder.joblib"))
        with open(os.path.join(d, "feature_schema.json")) as f:
            schema = json.load(f)
        # Only swap the globals once every artifact loaded successfully —
        # a partial reload (e.g. mid-retrain) must never leave the app
        # serving predictions with mismatched model/schema pairs.
        with _lock:
            _model, _calibrated, _label_enc, _schema = model, calibrated, label_enc, schema
            _load_error = None
            _model_version = f"xgboost_calibrated_{os.path.getmtime(os.path.join(d, 'payment_state_model.joblib')):.0f}"
    except FileNotFoundError as e:
        with _lock:
            _load_error = str(e)


_load()


def reload_model():
    """Called after auto-retraining completes (routers/simulation.py) to
    pick up the freshly written artifacts without a process restart."""
    _load()


def model_status() -> str:
    return "loaded" if _calibrated is not None else "not_trained"


def current_model_version() -> str:
    return _model_version


def predict_payment_state(features: dict) -> dict:
    """features must contain every key in _schema['feature_columns'].
    Returns probabilities over the trained classes plus a confidence score
    (max class probability) — never fabricated if the model isn't loaded.
    Reads under the same lock reload_model() writes under, so a request
    never sees a half-swapped model/schema pair mid-reload."""
    with _lock:
        calibrated, schema, model_version, load_error = _calibrated, _schema, _model_version, _load_error

    if calibrated is None:
        return {
            "success": None, "pending": None, "failed": None,
            "confidence": None, "model_version": "unavailable",
            "note": f"model not loaded: {load_error or 'artifacts missing, train first'}",
        }

    cols = schema["feature_columns"]
    encoders = schema["categorical_encoders"]
    row = {}
    for c in cols:
        v = features.get(c)
        if c in encoders:
            row[c] = encoders[c].get(str(v), 0)
        else:
            row[c] = float(v) if v is not None else 0.0
    X = pd.DataFrame([row], columns=cols)

    proba = calibrated.predict_proba(X)[0]
    classes = schema["classes"]
    dist = {cls.lower(): round(float(p), 4) for cls, p in zip(classes, proba)}
    for k in ("success", "pending", "failed"):
        dist.setdefault(k, 0.0)
    confidence = round(float(max(proba)), 4)
    return {**dist, "confidence": confidence, "model_version": model_version}
