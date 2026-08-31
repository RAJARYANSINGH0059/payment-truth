"""
Section 13: historical incident memory + similarity.

Deliberately NOT a vector database — spec explicitly says "use structured
similarity initially; do not add a vector database unless genuinely useful."
This compares a current incident's measurable attributes against every
stored IncidentMemory row using a simple weighted feature match, and
returns the closest ones with a similarity percentage plus which
attributes actually matched (so "87% similar to Incident #021" is always
explainable, never an opaque embedding distance).
"""
from dataclasses import dataclass


WEIGHTS = {
    "payment_method": 0.20,
    "bank": 0.20,
    "root_cause": 0.30,
    "failure_rate": 0.15,
    "duration_minutes": 0.15,
}


@dataclass
class SimilarIncident:
    incident_id: str
    similarity_pct: float
    matched_on: list
    recommended_action: str | None
    actual_outcome: str | None
    revenue_impact: float | None


def _closeness(a: float | None, b: float | None, tolerance: float) -> float:
    """Returns 0..1 — 1.0 if within tolerance, decaying linearly to 0 at 3x
    tolerance. Returns 0 if either value is missing (can't claim a match on
    absent data)."""
    if a is None or b is None:
        return 0.0
    diff = abs(a - b)
    if diff <= tolerance:
        return 1.0
    if diff >= tolerance * 3:
        return 0.0
    return 1.0 - (diff - tolerance) / (tolerance * 2)


def find_similar_incidents(current: dict, historical: list[dict], top_n=3) -> list[SimilarIncident]:
    """
    current / each item in historical: dict with keys payment_method, bank,
    root_cause, failure_rate, duration_minutes (any may be None/missing).
    """
    results = []
    for h in historical:
        score = 0.0
        matched_on = []

        if current.get("payment_method") and current["payment_method"] == h.get("payment_method"):
            score += WEIGHTS["payment_method"]
            matched_on.append(f"same payment method ({current['payment_method']})")

        if current.get("bank") and current["bank"] == h.get("bank"):
            score += WEIGHTS["bank"]
            matched_on.append(f"same bank ({current['bank']})")

        if current.get("root_cause") and current["root_cause"] == h.get("root_cause"):
            score += WEIGHTS["root_cause"]
            matched_on.append(f"same root cause ({current['root_cause']})")

        fr_closeness = _closeness(current.get("failure_rate"), h.get("failure_rate"), tolerance=0.05)
        if fr_closeness > 0:
            score += WEIGHTS["failure_rate"] * fr_closeness
            matched_on.append("similar failure rate")

        dur_closeness = _closeness(current.get("duration_minutes"), h.get("duration_minutes"), tolerance=15)
        if dur_closeness > 0:
            score += WEIGHTS["duration_minutes"] * dur_closeness
            matched_on.append("similar duration")

        results.append(SimilarIncident(
            incident_id=h["incident_id"],
            similarity_pct=round(score * 100, 1),
            matched_on=matched_on,
            recommended_action=h.get("recommended_action"),
            actual_outcome=h.get("actual_outcome"),
            revenue_impact=h.get("revenue_impact"),
        ))

    results.sort(key=lambda r: r.similarity_pct, reverse=True)
    return results[:top_n]
