"""
Prediction vs Reality (completion-prompt items 1-2): turns raw
prediction_json + eventual ground truth into an explicit CORRECT/INCORRECT
verdict, and aggregates that across every evaluated prediction into a
confusion matrix and accuracy figure — all computed live from the DB,
nothing hardcoded.
"""
from dataclasses import dataclass

CLASSES = ["SUCCESS", "PENDING", "FAILED"]

# True/observed final states map onto the model's 3 output classes.
# PENDING is included for schema completeness (spec section 28) even
# though the current simulator always eventually resolves to
# SUCCESS/FAILED — see docs/ASSUMPTIONS.md.
STATE_TO_CLASS = {
    "SUCCESS": "SUCCESS", "CAPTURED": "SUCCESS",
    "FAILED": "FAILED",
    "PENDING": "PENDING", "UNKNOWN": "PENDING",
}


@dataclass
class Verdict:
    predicted_class: str
    actual_class: str
    probability_of_actual_class: float | None
    was_correct: bool


def predicted_class_from(prediction_json: dict) -> str | None:
    if not prediction_json:
        return None
    probs = {c: prediction_json.get(c.lower()) for c in CLASSES}
    if all(v is None for v in probs.values()):
        return None
    return max(probs, key=lambda c: probs[c] or -1)


def evaluate(prediction_json: dict, actual_state: str | None) -> Verdict | None:
    """Returns None if either the prediction or the actual outcome isn't
    known yet — a payment mid-flight has nothing to evaluate, and that's
    reported as 'not yet resolved', never guessed."""
    if not actual_state:
        return None
    predicted = predicted_class_from(prediction_json)
    if predicted is None:
        return None
    actual_class = STATE_TO_CLASS.get(actual_state.upper(), actual_state.upper())
    prob_actual = (prediction_json or {}).get(actual_class.lower())
    return Verdict(
        predicted_class=predicted, actual_class=actual_class,
        probability_of_actual_class=prob_actual, was_correct=(predicted == actual_class),
    )


def aggregate(verdicts: list[Verdict]) -> dict:
    """Confusion matrix + summary stats over every resolved, evaluated
    prediction. Empty input returns a valid zeroed structure, never None —
    the /experiments page must render something even before any
    predictions have resolved."""
    matrix = {p: {a: 0 for a in CLASSES} for p in CLASSES}
    correct = 0
    confidences = []
    for v in verdicts:
        matrix[v.predicted_class][v.actual_class] += 1
        if v.was_correct:
            correct += 1
        if v.probability_of_actual_class is not None:
            confidences.append(v.probability_of_actual_class)

    total = len(verdicts)
    avg_confidence = round(sum(confidences) / len(confidences), 4) if confidences else None
    # Brier-style calibration check: mean squared error between the
    # probability assigned to the actual class and 1.0 (perfect
    # confidence) — lower is better-calibrated, not just more "confident".
    brier = (round(sum((1 - c) ** 2 for c in confidences) / len(confidences), 4)
             if confidences else None)

    return {
        "total_evaluated": total,
        "correct": correct,
        "incorrect": total - correct,
        "accuracy": round(correct / total, 4) if total else None,
        "average_confidence": avg_confidence,
        "brier_score": brier,
        "confusion_matrix": {"labels": CLASSES, "matrix": matrix},
    }
