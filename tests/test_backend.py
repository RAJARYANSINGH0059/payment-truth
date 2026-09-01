"""Run with: pytest tests/ -v (from repo root, after pip install -r backend/requirements.txt)"""
import hashlib
import hmac
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ.setdefault("DATABASE_URL", "sqlite:///./test_payment_truth.db")


@pytest.fixture
def client():
    os.environ["RAZORPAY_WEBHOOK_SECRET"] = "test_secret_123"
    os.environ.setdefault("ML_ARTIFACTS_DIR", os.path.join(os.path.dirname(__file__), "..", "ml", "artifacts"))
    from app.main import app
    from app.db import engine
    from app.models.db import Base
    from fastapi.testclient import TestClient

    # The app module (and its `engine`) is cached by Python after the first
    # import, so every test in this file shares one SQLite connection pool.
    # Deleting the DB file between tests doesn't reliably isolate them —an
    # already-open connection can keep reading/writing an unlinked inode,
    # letting one test's rows leak into the next. Explicitly wiping and
    # recreating the schema on the shared engine guarantees a clean slate
    # regardless of pooling behavior.
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)

    with TestClient(app) as c:
        yield c

    db_path = os.path.join(os.path.dirname(__file__), "..", "backend", "test_payment_truth.db")
    if os.path.exists(db_path):
        os.remove(db_path)


def test_health_ok_without_razorpay(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["razorpay"] in ("configured", "not_configured")


def test_webhook_rejects_bad_signature(client):
    body = json.dumps({"event": "payment.captured", "payload": {}}).encode()
    r = client.post("/api/webhooks/razorpay", content=body,
                     headers={"X-Razorpay-Signature": "garbage", "X-Razorpay-Event-Id": "evt_bad"})
    assert r.status_code == 400


def test_webhook_accepts_valid_signature_and_dedupes(client):
    secret = os.environ["RAZORPAY_WEBHOOK_SECRET"]
    payload = {"event": "payment.captured",
               "payload": {"payment": {"entity": {"id": "pay_ABC", "order_id": "order_ABC",
                                                    "amount": 99900, "method": "upi"}}}}
    body = json.dumps(payload).encode()
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    r1 = client.post("/api/webhooks/razorpay", content=body,
                      headers={"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": "evt_1"})
    assert r1.status_code == 200
    assert r1.json()["status"] == "accepted"

    r2 = client.post("/api/webhooks/razorpay", content=body,
                      headers={"X-Razorpay-Signature": sig, "X-Razorpay-Event-Id": "evt_1"})
    assert r2.json()["status"] == "duplicate_ignored"


def test_webhook_rejects_when_secret_not_configured(client, monkeypatch):
    from app.config import settings
    monkeypatch.setattr(settings, "RAZORPAY_WEBHOOK_SECRET", "")
    r = client.post("/api/webhooks/razorpay", content=b"{}",
                     headers={"X-Razorpay-Signature": "x", "X-Razorpay-Event-Id": "evt_x"})
    assert r.status_code == 503


def test_decision_engine_four_scenarios():
    from app.decision_engine import decide
    assert decide(0.35, 0.4, 0.25, True, 0.4, 1200, False, 0.6) == "STOP"
    assert decide(0.85, 0.1, 0.05, False, 0.0, 500, False, 0.9) == "WAIT"
    assert decide(0.5, 0.3, 0.2, False, 0.0, 500, True, 0.9) == "VERIFY"
    assert decide(0.1, 0.1, 0.8, False, 0.0, 900, False, 0.85) == "RECOVER"


def test_leakage_columns_rejected():
    from data.schemas.leakage_columns import assert_no_leakage
    with pytest.raises(ValueError):
        assert_no_leakage(["amount", "true_final_state"])
    assert_no_leakage(["amount", "payment_method"])  # should not raise


def test_csv_import_validates_and_scores(client):
    import io
    csv_content = (
        b"payment_id,amount,payment_method,bank,observed_status,ground_truth_final_state\n"
        b"P900001,999.00,UPI,BANK_A,SUCCESS,SUCCESS\n"
        b"P900002,499.00,CARD,BANK_B,FAILED,FAILED\n"
        b"P900003,,CARD,BANK_B,FAILED,FAILED\n"          # missing amount -> invalid
        b"P900001,199.00,UPI,BANK_C,SUCCESS,SUCCESS\n"    # duplicate id -> invalid
    )
    files = {"file": ("upload.csv", io.BytesIO(csv_content), "text/csv")}
    r = client.post("/api/data/import", files=files)
    assert r.status_code == 200
    body = r.json()
    assert body["payments_recognized"] == 2
    assert body["invalid_rows"] == 2
    assert body["ground_truth_present"] is True
    assert body["evaluation"]["accuracy"] == 1.0


def test_csv_import_without_ground_truth_never_scores(client):
    import io
    csv_content = b"payment_id,amount,payment_method\nP1,100,UPI\n"
    files = {"file": ("upload.csv", io.BytesIO(csv_content), "text/csv")}
    r = client.post("/api/data/import", files=files)
    assert r.status_code == 200
    body = r.json()
    assert body["ground_truth_present"] is False
    assert body["evaluation"] is None


def test_historical_similarity_ranks_closest_match_first():
    from app.historical_similarity import find_similar_incidents
    current = {"payment_method": "UPI", "bank": "BANK_A", "root_cause": "BANK_SPECIFIC",
               "failure_rate": 0.31, "duration_minutes": 22}
    historical = [
        {"incident_id": "INC021", "payment_method": "UPI", "bank": "BANK_A",
         "root_cause": "BANK_SPECIFIC", "failure_rate": 0.29, "duration_minutes": 25,
         "recommended_action": "STOP", "actual_outcome": "resolved", "revenue_impact": 185000},
        {"incident_id": "INC014", "payment_method": "CARD", "bank": "BANK_C",
         "root_cause": "WEBHOOK_PROCESSING", "failure_rate": 0.10, "duration_minutes": 60,
         "recommended_action": "VERIFY", "actual_outcome": "false alarm", "revenue_impact": 0},
    ]
    results = find_similar_incidents(current, historical)
    assert results[0].incident_id == "INC021"
    assert results[0].similarity_pct > results[1].similarity_pct
    assert "same bank (BANK_A)" in results[0].matched_on


def test_simulation_generate_actually_populates_the_live_app(client):
    """The critical end-to-end check: hitting /api/simulation/generate must
    not just write CSVs to disk — it must load real scored payments (via
    the real trained model) into the DB, or every other page in the app
    stays empty forever. This is the regression test for that gap."""
    r = client.post("/api/simulation/generate", params={"payments": 200, "seed": 3, "sim_days": 1})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["loaded_into_app"]["payments_loaded"] > 0

    payments = client.get("/api/payments?limit=5").json()
    assert len(payments) > 0
    pid = payments[0]["payment_id"]

    detail = client.get(f"/api/payments/{pid}").json()
    assert len(detail["timeline"]) > 0
    prediction = detail["timeline"][0]["prediction"]
    assert prediction["model_version"] is not None  # a real model produced this, not a stub
    assert detail["timeline"][0]["recommendation"] in ("WAIT", "VERIFY", "RECOVER", "STOP")

    import os as _os
    generated_dir = _os.path.join(_os.path.dirname(__file__), "..", "data", "demo")
    for f in ("payments.csv", "payment_events.csv", "observation_snapshots.csv"):
        assert _os.path.exists(_os.path.join(generated_dir, f))


def test_simulation_generate_reaches_all_four_decisions(client):
    """Regression test for a real gap found during manual verification:
    incident detection ran independently of per-payment scoring, so STOP
    was never actually reachable even though decision_engine supports it.
    A big-enough generation run should exercise all four decisions from
    real data, not just WAIT/VERIFY."""
    r = client.post("/api/simulation/generate", params={"payments": 3000, "seed": 7, "sim_days": 2})
    assert r.status_code == 200
    assert r.json()["loaded_into_app"]["payments_loaded"] > 0

    payments = client.get("/api/payments?limit=3000").json()
    decisions = set()
    for p in payments:
        detail = client.get(f"/api/payments/{p['payment_id']}").json()
        if detail["timeline"]:
            decisions.add(detail["timeline"][0]["recommendation"])
    assert decisions == {"WAIT", "VERIFY", "RECOVER", "STOP"}


def test_prediction_vs_reality_computes_real_verdicts(client):
    """The verdict (CORRECT/INCORRECT) must actually be computed, not just
    left as an unused schema field — this was a real gap found during
    audit (Prediction.was_correct existed but nothing ever set it)."""
    r = client.post("/api/simulation/generate", params={"payments": 1000, "seed": 3, "sim_days": 1})
    assert r.status_code == 200

    payments = client.get("/api/payments?limit=1000").json()
    found_verdict = False
    for p in payments[:50]:
        detail = client.get(f"/api/payments/{p['payment_id']}").json()
        for entry in detail["timeline"]:
            if entry["verdict"] is not None:
                found_verdict = True
                assert entry["verdict"]["predicted_class"] in ("SUCCESS", "PENDING", "FAILED")
                assert entry["verdict"]["actual_class"] in ("SUCCESS", "PENDING", "FAILED")
                assert isinstance(entry["verdict"]["was_correct"], bool)
    assert found_verdict, "expected at least one resolved prediction with a computed verdict"

    agg = client.get("/api/experiments/prediction-vs-reality").json()
    assert agg["total_evaluated"] > 0
    assert agg["correct"] + agg["incorrect"] == agg["total_evaluated"]
    assert 0.0 <= agg["accuracy"] <= 1.0


def test_explain_endpoint_falls_back_deterministically(client):
    """No LLM key configured in test env -> must return a real, coherent
    explanation and honestly label its source, never silently blank."""
    r = client.post("/api/explain", json={
        "prediction": "PENDING", "probabilities": {"success": 0.11, "pending": 0.82, "failed": 0.07},
        "evidence": ["high_webhook_delay", "late_capture_pattern"], "recommendation": "VERIFY",
    })
    assert r.status_code == 200
    body = r.json()
    assert body["source"] == "DETERMINISTIC_FALLBACK"
    assert "pending" in body["explanation"].lower()
    assert len(body["explanation"]) > 20


def test_generator_config_actually_changes_output():
    """The --config flag must genuinely change generated data, not just
    be a label used for hashing — this was a real gap found during audit
    (--config was accepted but never loaded)."""
    import subprocess
    import sys as _sys
    import tempfile
    import pandas as pd
    import os as _os

    repo_root = _os.path.join(_os.path.dirname(__file__), "..")
    with tempfile.TemporaryDirectory() as default_dir, tempfile.TemporaryDirectory() as stress_dir:
        for config_name, out_dir in [("default", default_dir), ("stress", stress_dir)]:
            subprocess.run(
                [_sys.executable, "scripts/generate_dataset.py", "--payments", "800", "--seed", "1",
                 "--sim-days", "1", "--config", config_name, "--out-dir", out_dir],
                cwd=repo_root, check=True, capture_output=True, text=True,
            )
        default_payments = pd.read_csv(_os.path.join(default_dir, "payments.csv"))
        stress_payments = pd.read_csv(_os.path.join(stress_dir, "payments.csv"))
        default_fail_rate = (default_payments["true_final_state"] == "FAILED").mean()
        stress_fail_rate = (stress_payments["true_final_state"] == "FAILED").mean()
        # stress.yaml has higher failure-rate ranges than default.yaml —
        # the two runs must actually differ, not silently produce identical data.
        assert stress_fail_rate > default_fail_rate
