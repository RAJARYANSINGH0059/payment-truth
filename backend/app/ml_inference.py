"""
Loads ml/artifacts/* once at startup and exposes predict_payment_state().
The deployed app loads the existing model — it never retrains on request
(section 47). If artifacts are missing (fresh clone, model not yet
trained), predict_payment_state() returns a clearly-labeled fallback
instead of crashing, so Simulation Mode still runs end-to-end.
"""
import json
import os

import joblib
import pandas as pd

from .config import settings

_model = None
_calibrated = None
_label_enc = None
_schema = None
_load_error = None


def _load():
    global _model, _calibrated, _label_enc, _schema, _load_error
    d = settings.ML_ARTIFACTS_DIR
    try:
        _model = joblib.load(os.path.join(d, "payment_state_model.joblib"))
        _calibrated = joblib.load(os.path.join(d, "probability_calibrator.joblib"))
        _label_enc = joblib.load(os.path.join(d, "label_encoder.joblib"))
        with open(os.path.join(d, "feature_schema.json")) as f:
            _schema = json.load(f)
    except FileNotFoundError as e:
        _load_error = str(e)


_load()


def model_status() -> str:
    return "loaded" if _calibrated is not None else "not_trained"


def predict_payment_state(features: dict) -> dict:
    """features must contain every key in _schema['feature_columns'].
    Returns probabilities over the trained classes plus a confidence score
    (max class probability) — never fabricated if the model isn't loaded."""
    if _calibrated is None:
        return {
            "success": None, "pending": None, "failed": None,
            "confidence": None, "model_version": "unavailable",
            "note": f"model not loaded: {_load_error or 'artifacts missing, train first'}",
        }

    cols = _schema["feature_columns"]
    encoders = _schema["categorical_encoders"]
    row = {}
    for c in cols:
        v = features.get(c)
        if c in encoders:
            row[c] = encoders[c].get(str(v), 0)
        else:
            row[c] = float(v) if v is not None else 0.0
    X = pd.DataFrame([row], columns=cols)

    proba = _calibrated.predict_proba(X)[0]
    classes = _schema["classes"]
    dist = {cls.lower(): round(float(p), 4) for cls, p in zip(classes, proba)}
    for k in ("success", "pending", "failed"):
        dist.setdefault(k, 0.0)
    confidence = round(float(max(proba)), 4)
    return {**dist, "confidence": confidence, "model_version": "xgboost_calibrated_v1"}
