"""
LLM explanation layer (completion-prompt items 19-24). Turns already-
computed structured facts into a natural-language explanation — it never
computes the facts themselves. If no LLM key is configured, or the call
fails for any reason, falls back to a deterministic template so the page
never goes blank and never silently pretends a template is an LLM output.
"""
import os
from dataclasses import dataclass

from .config import settings


@dataclass
class Explanation:
    text: str
    source: str  # "LLM" or "DETERMINISTIC_FALLBACK"


def _deterministic_explanation(payload: dict) -> str:
    """Template-based explanation built only from the structured fields
    already computed elsewhere (prediction probabilities, evidence,
    recommendation) — never invents a number that isn't in the payload."""
    prediction = payload.get("prediction", "UNKNOWN")
    probs = payload.get("probabilities", {})
    evidence = payload.get("evidence", [])
    recommendation = payload.get("recommendation")

    top_prob = None
    if probs:
        key = prediction.lower() if isinstance(prediction, str) else None
        top_prob = probs.get(key) if key else max(probs.values(), default=None)

    parts = []
    if prediction and top_prob is not None:
        parts.append(f"This payment is currently most likely to end up {prediction.lower()} "
                      f"({round(top_prob * 100)}% probability based on what's known so far).")
    elif prediction:
        parts.append(f"This payment is currently predicted to be {prediction.lower()}.")

    if evidence:
        readable = ", ".join(str(e).replace("_", " ") for e in evidence[:3])
        parts.append(f"The main signals behind this are: {readable}.")

    if recommendation == "WAIT":
        parts.append("Since there's still a real chance this resolves on its own, "
                      "waiting is safer than acting now.")
    elif recommendation == "VERIFY":
        parts.append("Because the evidence is mixed or confidence is low, verifying "
                      "with an authoritative source is safer than guessing.")
    elif recommendation == "RECOVER":
        parts.append("The failure signal is strong enough that initiating recovery "
                      "is likely worth it.")
    elif recommendation == "STOP":
        parts.append("Given an active incident, automatic action is paused to avoid "
                      "adding risk while the underlying issue is ongoing.")

    if not parts:
        return "Not enough structured information was provided to generate an explanation."
    return " ".join(parts)


def _call_llm_provider(payload: dict) -> str | None:
    """OpenAI-compatible provider. Returns None (never raises) on any
    failure — missing key, network error, timeout, bad response — so the
    caller always has a safe path to the deterministic fallback."""
    if settings.LLM_PROVIDER != "openai" or not settings.LLM_API_KEY:
        return None
    try:
        import httpx
        prompt = (
            "Explain this payment prediction in 2-3 plain sentences for a merchant. "
            "Only use the facts given below — do not invent numbers or change the "
            "recommendation.\n\n"
            f"Prediction: {payload.get('prediction')}\n"
            f"Probabilities: {payload.get('probabilities')}\n"
            f"Evidence: {payload.get('evidence')}\n"
            f"Recommendation: {payload.get('recommendation')}"
        )
        resp = httpx.post(
            "https://api.openai.com/v1/chat/completions",
            headers={"Authorization": f"Bearer {settings.LLM_API_KEY}"},
            json={"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}],
                  "max_tokens": 150, "temperature": 0.3},
            timeout=8.0,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return None


def explain(payload: dict) -> Explanation:
    """payload: {"prediction": str, "probabilities": dict, "evidence": list,
    "recommendation": str}. Never lets the LLM change any of these fields —
    it only reads them to produce text."""
    llm_text = _call_llm_provider(payload)
    if llm_text:
        return Explanation(text=llm_text, source="LLM")
    return Explanation(text=_deterministic_explanation(payload), source="DETERMINISTIC_FALLBACK")
