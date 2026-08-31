# Simulation Assumptions

This file documents every assumption baked into `data/generators/generate_dataset.py`
so nobody mistakes synthetic behavior for measured Razorpay production behavior
(spec sections 13/20/23/82).

## Not claimed to be real Razorpay data

- **Webhook delivery delay distribution** (`sample_delivery_delay`) is a
  lognormal distribution with a rare heavy tail, chosen because it's a common,
  reasonable shape for network/queue delays — not because it was measured
  against Razorpay's actual production webhook latency. Razorpay's own docs
  state webhooks may be delayed and may arrive out of order, out-of-order and
  duplicate handling; the specific delay numbers here are ours.
- **Bank baseline failure rates and latencies** (`build_banks`) are drawn from
  uniform ranges chosen to be plausible, not sourced from any real bank's
  measured performance. Bank names (`BANK_A`..`BANK_E`) are placeholders, not
  real institutions.
- **Incident shapes** (ramp-up/peak/recovery, duration, severity) are
  parameterized randomly per spec section 25, not fit to any real incident log.
- **Customer/merchant profile distributions** are synthetic archetypes (new,
  repeat, high-frequency, etc.) with made-up baseline rates, not derived from
  real user cohorts.
- **Payment-method mix per merchant type** (e.g. "upi_heavy" merchants get 3x
  UPI weighting) is a simplifying heuristic, not measured segment data.

## Documented simplifications

- The model's target classes are `SUCCESS` / `PENDING` / `FAILED` per spec,
  but the current simulator always resolves every payment to a final
  `CAPTURED` or `FAILED` state — there is no "genuinely never resolves"
  branch yet. In practice this means `PENDING` never appears as a
  `final_observed_state` label in the committed dataset; it still appears as
  an *observed-at-snapshot* status while a payment is unresolved. Extending
  the simulator with truly-unresolved payments is a natural Phase-1.5
  addition if the judges want to see it.
- The incident detector's `webhook_latency_mean_ms` health feature is
  approximated from `capture_delay_sec * 200` rather than a directly
  simulated webhook-latency time series, because per-minute webhook latency
  isn't currently persisted to `payments.csv`. This is a placeholder signal,
  not a claim of measured webhook latency.
- Health-metric bins for the incident detector are aggregated over
  `bin_minutes` (default 10) rather than a literal 1-minute window, because
  at this dataset's synthetic traffic volume a true 1-minute bin is too
  sparse for failure-rate to carry signal above sampling noise. This is
  called out explicitly in `ml/pipeline/incident_detector.py` rather than
  silently relabeling coarse bins as "1m" features.

## What IS grounded in Razorpay's own documentation (not assumptions)

- At-least-once webhook delivery → dedupe via `x-razorpay-event-id`.
- Webhook events may be delivered out of order.
- Webhook signature validation uses raw-body HMAC-SHA256 against the
  configured webhook secret, distinct from the API key secret.
- Webhook responses must return 2xx quickly; heavy processing happens after
  the response (implemented via FastAPI `BackgroundTasks` in
  `backend/app/routers/webhooks.py`).
- Localhost cannot receive Razorpay webhooks — a public HTTPS endpoint is
  required, which is why Razorpay Test Mode integration is a separate,
  user-driven deployment step (see README "Enabling Razorpay Test Mode").
