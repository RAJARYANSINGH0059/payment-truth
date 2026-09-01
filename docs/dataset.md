# Dataset — Payment Truth

## Two sources, never mixed

Every record carries `source = SYNTHETIC` or `source = RAZORPAY_TEST`.
Synthetic data is the entire ML training/evaluation set; Razorpay Test
Mode data is used only to validate the real integration (signature
validation, dedup, normalization) — it is never used to train the model.
See spec section 6 / section 49 of the original build prompts.

## True world vs. observed world

The simulator (`data/generators/generate_dataset.py`) builds the TRUE
final state of a payment first, then separately simulates event
generation, delivery delay, and merchant observation. The model only ever
sees the observed side at prediction time — enforced by
`data/schemas/leakage_columns.py` + `assert_no_leakage()`.

## What's config-driven vs. what's a documented synthetic assumption

**Config-driven** (`data/config/{default,stress,demo,unseen_test}.yaml`):
bank failure-rate/latency ranges, customer success-rate ranges, incident
count/severity/duration ranges, event-delivery delay/duplicate/out-of-order
probabilities, late-capture/hard-negative probabilities.

**DOCUMENTED RAZORPAY BEHAVIOR** (not assumptions — grounded in Razorpay's
own public docs, see `docs/ASSUMPTIONS.md`):
- At-least-once webhook delivery → dedupe via `x-razorpay-event-id`
- Webhook events may arrive out of order
- Raw-body HMAC-SHA256 signature validation, separate from the API key secret
- Webhooks must return 2xx within Razorpay's response window; heavy work happens after

**OUR SYNTHETIC ASSUMPTION** (explicitly not claimed as measured Razorpay
production data): the exact shape of the lognormal delivery-delay
distribution, bank names/failure-rate values (`BANK_A`..`BANK_E` are
placeholders), customer/merchant archetype distributions, and the
incident ramp-up/peak/recovery timing model. All of these are reasonable,
documented choices — not measurements.

## Event timeline

Every payment has `created_at`, per-event `event_time` (true) and
`received_time` (delivery-delayed, separately sampled), `resolved_at`.
Observation snapshots are built at fixed offsets (5s/15s/30s/60s/180s/600s)
containing only events received by that timestamp — the model trains on
the earliest snapshot per payment, matching what a merchant would
actually know moments after a payment starts (see
`backend/app/simulation_loader.py`'s docstring for why the earliest, not
latest, snapshot is what the live app scores).

## Scenario coverage

Genuine failure, late capture (observed failure/pending, true eventual
capture — sometimes with a misleading early failed-looking event),
duplicate webhook delivery, out-of-order delivery, hard negatives (normal
traffic that looks suspicious but isn't), and latent incidents with
ramp-up/peak/recovery shape affecting bank/method/merchant failure rates
without ever exposing the cause as a feature.

## Reproducibility

```bash
python scripts/generate_dataset.py --payments 100000 --seed 42 --config default
```
Same `--seed` + `--config` → identical dataset (verified: two runs with
the same seed produce byte-identical CSVs). `generator_version` and a
`config_hash` are printed on every run for provenance tracking.

## Razorpay Test Mode validation

Separate from the synthetic pipeline entirely — see README "Enabling
Razorpay Test Mode" for the exact steps. Test Mode data validates the
webhook parser, signature verification, dedup, and API-verification
fallback against genuine Razorpay payloads. It is never bulk-collected to
train the model (spec section 42/49 explicitly prohibits this).
