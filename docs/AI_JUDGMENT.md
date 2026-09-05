# AI Judgment — Where AI Is Used, and Where It Deliberately Isn't

Razorpay's own bar for this criterion: *"utilizing AI models appropriately
while opting for deterministic solutions where AI is unnecessary."* Every
component below was assigned to ML, a deterministic rule, or an LLM
specifically because of what that technique is actually good at — not by
default.

## Uses ML (XGBoost) — because this is a genuine pattern-recognition problem

**Payment-state prediction** (`ml/pipeline/train.py`). Given partial,
noisy, correlated signals (event timing, delivery delay, customer/merchant
history), predict the eventual payment outcome. This has no clean rule —
"if webhook delayed > 5s then PENDING" would be a guess, not a model.
XGBoost was chosen over deep learning deliberately: tabular data, fast
CPU-only training, and — critically for a financial decision system —
SHAP explainability. Compared against three baselines (majority-class,
rule-based, Logistic Regression) so the ML choice has to earn its place;
it beats the best baseline 0.97 vs 0.65 macro F1.

**Incident anomaly detection** (`ml/pipeline/incident_detector.py`,
Isolation Forest). Detecting a failure-rate spike that doesn't match a
fixed threshold is a genuine unsupervised-anomaly problem. Compared
against a simple rule-based threshold detector honestly — the ML model
wins by only a small margin at this project's traffic volume, and that
margin is reported plainly rather than exaggerated (see `docs/ml-results.md`).

## Deliberately deterministic — because a financial decision needs to be

**The decision engine** (`backend/app/decision_engine.py::decide`). This
is the component that actually recommends WAIT/VERIFY/RECOVER/STOP — the
one action a merchant might actually take. It is pure Python `if`/`elif`
logic, not a model. Why: a financial action needs to be **auditable and
reproducible** — the same inputs must always produce the same decision,
and a human must be able to trace *exactly* why STOP was chosen instead
of WAIT, in a way "the neural network activated" never allows. This is
the single most important AI-judgment call in the whole project: the
highest-stakes decision is the one place ML was *not* used.

**Root-cause diagnosis** (`decision_engine.py::diagnose_root_cause`).
Evidence-scored, not model-inferred: "Bank A failure rate 4.4x baseline,
other banks normal" → `BANK_SPECIFIC`. A classifier could learn this
association, but a scored rule can be *inspected* — every diagnosis
returns its supporting and contradicting evidence, not just a label.

**Financial-impact calculation** (`compute_financial_impact`). Plain
arithmetic (exposure × failure probability × recovery probability), with
every number tagged `VERIFIED` / `ESTIMATED` / `PREDICTED` / `SIMULATED`
so a merchant is never shown a made-up number without knowing its
confidence category. No model output here at all — deliberately.

**Webhook signature validation, deduplication, out-of-order tolerance**
(`webhook_utils.py`, `routers/webhooks.py`). Pure security/correctness
logic (HMAC comparison, event-ID lookup, precedence rules). There is no
version of this that should ever involve a model — a payment webhook's
authenticity is a cryptographic fact, not a probabilistic one.

## Uses an LLM — narrowly, for exactly one job: turning facts into prose

`backend/app/llm_explain.py`. The LLM's *only* input is already-computed
structured facts (prediction, probabilities, evidence, recommendation),
and its *only* output is a sentence or two of natural language. It cannot
change a probability, a recommendation, or a financial figure — that
would hand a auditable financial decision to a non-deterministic system,
which is exactly the mistake this project's whole architecture is built
to avoid. If no LLM key is configured, or the call fails for any reason,
a deterministic template produces the same category of explanation from
the same facts — the explanation always has a labeled `source`
(`LLM` or `DETERMINISTIC_FALLBACK`), so nothing is silently faked.

## The recovery workflow itself is deterministic — not an agent

`backend/app/recovery_engine.py` is the ACT step: it executes the
decisions the rules already made. It is deliberately *not* an
open-ended agent — every branch (execute / escalate / block) is a
plain if/else against a fixed threshold, run inside a single
transaction, with no loop, no planning, and no ability to decide to
retry more than `MAX_ATTEMPTS_PER_PAYMENT` times regardless of outcome.
The escalation thresholds (transaction value, model confidence) and the
batch exposure cap are the "compliant escalation" and "stopping rules"
the Track 3 bar explicitly asks for — a real payments product without
these would be committing to real money movement based on a
probabilistic prediction alone, which is precisely the mistake this
project's whole architecture is designed to avoid.

## The one-line summary

**ML predicts. Rules decide. An LLM (optionally) narrates. Bounded
rules execute — never an open-ended agent.** Nothing downstream of a
financial action depends on a model that can't be inspected or
reproduced.
