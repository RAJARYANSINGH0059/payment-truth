"""Model & incident-detector metrics — reads ml/artifacts/*.json, never hardcoded."""

import os

from fastapi import APIRouter

from ..config import settings
from ..ml_inference import model_status

router = APIRouter(prefix="/api")

@router.get("/models/metrics")
def models_metrics():
    """Section 65 — reads the metrics.json written by ml/pipeline/train.py
    and incident_detector.py. Never hardcoded."""
    import json
    import os
    out = {}
    for name, fname in [("payment_state_model", "metrics.json"),
                         ("incident_detector", "incident_detector_metrics.json")]:
        path = os.path.join(settings.ML_ARTIFACTS_DIR, fname)
        if os.path.exists(path):
            with open(path) as f:
                out[name] = json.load(f)
        else:
            out[name] = {"status": "not yet trained"}
    out["model_status"] = model_status()
    return out
