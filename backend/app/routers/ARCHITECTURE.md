# Backend Router Organization

`backend/app/routers/` is split by responsibility, not by HTTP verb or by
entity alone — each file owns one coherent slice of the product:

| File | Owns | Endpoints |
|---|---|---|
| `webhooks.py` | Inbound Razorpay events | `POST /api/webhooks/razorpay` |
| `payments.py` | Core payment entity | `GET /api/payments`, `GET /api/payments/{id}` |
| `incidents.py` | Core incident entity + historical similarity | `GET /api/incidents`, `GET /api/incidents/{id}` |
| `dashboard.py` | Cross-entity aggregates for the Overview/Audit pages | `GET /api/overview`, `GET /api/audit` |
| `models_metrics.py` | ML reporting (reads `ml/artifacts/*.json`) | `GET /api/models/metrics` |
| `simulation.py` | Getting data INTO the app (generate or upload) | `POST /api/simulation/generate`, `POST /api/data/import` |
| `experiments.py` | Formal evaluation + LLM explanation | `GET /api/experiments/*`, `POST /api/explain` |
| `razorpay.py` | Outbound Razorpay Test Mode calls | `GET /api/razorpay/status`, `POST /api/razorpay/test-order`, `GET /api/razorpay/verify/{id}` |

## Why this split

Before this reorganization, every endpoint lived in a single 400+ line
`api.py`. That made it hard to find anything and meant one file's blast
radius covered the whole API surface. The boundary chosen here follows
the product's own conceptual seams (spec section 2's OBSERVE → UNDERSTAND
→ PREDICT → ACT → LEARN loop): `payments`/`incidents` are what's being
observed, `dashboard` is understanding at a glance, `simulation` is how
data enters the system, `experiments` is the LEARN stage, `razorpay` is
the one module that talks to an external system.

## Rules for adding a new endpoint

- Touches one payment or one incident by ID → `payments.py` / `incidents.py`
- Aggregates across many payments/incidents for a summary view → `dashboard.py`
- Reads a `ml/artifacts/*.json` or `experiments/*/metrics.json` file → `models_metrics.py` or `experiments.py`
- Calls out to Razorpay's API → `razorpay.py`
- Doesn't fit cleanly anywhere above → discuss the boundary before adding
  a catch-all file; that's exactly the pattern this reorg was fixing.

All routers share the same `/api` prefix (set per-router, not globally in
`main.py`) and are wired together in `backend/app/main.py`.
