# Failure Recovery Log

This is a running, honest record of what actually broke during development
and how it was found and fixed — not a polished retrospective written
after the fact. Every entry below was caught by actually running the
system end-to-end, not by reading the code and assuming it worked.

## 1. "Generate Data" wrote files but never populated the app

**What broke:** The Simulation page's "Generate Data" button called the
synthetic generator, which wrote `payments.csv` etc. to disk — but nothing
loaded that data back into the running application. A judge clicking
"Generate Data" then "Payments" would see an empty list forever.

**How it was found:** Ran the full flow manually instead of trusting that
"the generator works" meant "the app works." The Payments page stayed
empty after generation.

**Fix:** Built `backend/app/simulation_loader.py` — scores every generated
payment with the actual trained model, runs it through the actual decision
engine, and detects incidents from the actual generated data. Closes
OBSERVE → PREDICT → ACT end to end.

## 2. STOP was implemented but structurally unreachable

**What broke:** The decision engine supports `STOP` for active incidents,
but incident detection ran as a separate pass *after* per-payment scoring.
No payment was ever scored with knowledge that an incident was active, so
`STOP` could never actually fire — even though the code for it was
correct and tested in isolation.

**How it was found:** After fixing #1, checked the actual distribution of
decisions across a real generated batch. Saw `WAIT`/`VERIFY`/`RECOVER`
but zero `STOP`, despite incidents being detected.

**Fix:** Reordered the pipeline — incident scan now runs first, and each
payment's decision looks up whether its time window falls inside a
detected incident. Verified: a 3,000-payment run now produces
`WAIT 2599 · VERIFY 279 · RECOVER 81 · STOP 41` — all four decisions
reachable from real data.

## 3. "Uncertain Payments" would always show ~0

**What broke:** Payments were loaded using their *last* observation
snapshot — by which point almost everything had already resolved to
SUCCESS/FAILED. The Overview page's "Uncertain Payments" metric would
sit at zero forever, defeating the entire premise of a system built to
predict under uncertainty.

**How it was found:** Manually inspected the Overview numbers after a
generation run and asked "does this actually demonstrate uncertainty?"
It didn't.

**Fix:** Switched to the *earliest* snapshot — what a merchant would
actually see moments after a payment starts. Verified: the same 3,000
payment run went from 0 uncertain payments to 2,465.

## 4. Router reorganization silently dropped an import

**What broke:** Splitting one 400-line `api.py` into 8 focused files
(for Build Quality) accidentally dropped a `datetime` import that the
CSV/JSON upload endpoint needed. It only failed on a CSV row that
included a `created_at` column — a case the existing test suite didn't
cover at the time.

**How it was found:** A dedicated post-refactor audit that tested every
endpoint with realistic inputs, not just the inputs the old tests
happened to use.

**Fix:** Restored the import, and added
`test_csv_import_handles_created_at_column` to the suite so this
specific regression can never silently return.

## 5. A test-isolation bug that would have hidden #4 and worse

**What broke:** pytest's `client` fixture reused one SQLite connection
across all tests (Python caches the `app.db` module after first import).
Deleting the DB file between tests didn't reliably reset state — a
stale open connection could keep referencing the old, unlinked file,
letting one test's rows leak into the next.

**How it was found:** A new end-to-end test failed inconsistently
depending on what ran before it in the same pytest session — a classic
symptom of shared, unreset state.

**Fix:** The fixture now explicitly `drop_all` + `create_all`s the shared
engine's schema before every test, guaranteeing a clean slate regardless
of connection pooling behavior.

## 6. The "Pay with Razorpay" button did nothing visible

**What broke:** The backend correctly created a Razorpay Test order, but
no actual Razorpay Checkout popup was ever wired up on the frontend —
clicking the button silently created an order and showed raw JSON, with
no payment modal for a user to complete.

**How it was found:** The user reported it directly after deployment;
reproducing the code path confirmed the popup was never actually
implemented, only the order-creation half.

**Fix:** Integrated Razorpay's real `checkout.js`, with the Key ID
(safe to expose client-side, unlike the Secret) surfaced through
`/api/razorpay/status`. The popup now genuinely opens, and the response
explicitly explains why the client-side success callback is *not*
trusted alone — only the server-side, signature-verified webhook is
authoritative (see README "Enabling Razorpay Test Mode").

## 7. Deployment tooling mistakes (human side, documented because they're
   part of the same build process)

- Ran `git add .` from a home directory instead of the project folder,
  which would have staged and nearly pushed personal browser/IDE data to
  a public repo. Caught before any commit completed, thanks to an
  unrelated git error stopping it. Fixed by never assuming a working
  directory without checking `git status` first.
- A file-move mistake while repackaging a delivery zip deleted a day's
  worth of new work (historical similarity, CSV import). Recovered by
  reconstructing the exact same code from what had already been
  written and verified minutes earlier, then re-verifying it identically.

## 8. sklearn version mismatch — committed model trained under a different library version than a fresh install would get

**What broke:** `backend/requirements.txt` pinned ML dependencies loosely
(`scikit-learn>=1.5`), so the committed `ml/artifacts/*.joblib` files —
pickled objects tied to the exact library version that trained them —
could silently mismatch whatever version a fresh `pip install` actually
pulls. Every app startup logged an `InconsistentVersionWarning`, and a
sufficiently different version could in principle produce subtly
different predictions than the ones actually validated.

**How it was found:** Testing with real credentials surfaced the warning
directly in the console output — easy to miss if you're only reading
JSON responses, not scanning stderr.

**Fix:** Pinned every ML dependency (`pandas`, `numpy`, `scikit-learn`,
`xgboost`, `shap`, `joblib`) to the exact version installed in the
environment used to test the app, then retrained the committed model in
that same environment so artifact and requirements file are genuinely
consistent. Verified with `warnings.simplefilter("error")` — proved zero
warnings remain, not just "looks fine" from casual output.

## 9. Razorpay API failures leaked a raw Python traceback to the client

**What broke:** Testing order creation with real (if sandbox-network-
blocked) credentials surfaced an unhandled exception from the Razorpay
SDK call — the endpoint had no catch-all for anything beyond "not
configured," so any network error, timeout, or Razorpay-side failure
propagated as a raw 500 with a full stack trace in the response body.

**How it was found:** Actually attempting a live order-creation call
with real credentials, not just testing the "not configured" path that
existing tests already covered.

**Fix:** Both `create_demo_order` and `verify_payment` now catch the
broader exception case, log the real error server-side, and return a
clean `502` with a plain-English message — deliberately broad because
this is the boundary to an external, unreliable network service where
the caller can't act differently on the specific failure mode anyway.
Locked in with `test_razorpay_order_failure_never_leaks_a_traceback`.

## 10. Docker image missing the experiments/ directory (same bug class as #1's Docker gap, caught by re-checking)

**What broke:** `backend/Dockerfile` copied `backend/`, `data/`, `ml/`, and
`scripts/` into the image — but not `experiments/`. The three formal
experiment endpoints (`/api/experiments/unseen-incident`, `/memory`,
`/revenue`) read their results from `experiments/*/metrics.json` at
runtime. In an actual deployed container, all three would have silently
returned "not yet run" even though the results are committed to the repo
and work perfectly locally.

**How it was found:** A deliberate re-check specifically looking for the
*same class* of bug already found once before (the earlier missing
`scripts/` COPY, entry-adjacent to #1) — Docker COPY omissions don't
announce themselves locally, since the whole repo is present outside a
container. Cross-referencing every file the app reads at runtime against
every Dockerfile COPY line caught it.

**Fix:** Added `COPY experiments/ ./experiments/` to `backend/Dockerfile`.

## 11. JSON dataset upload silently mis-scored heterogeneous rows

**What broke:** CSV uploads always have a uniform header, so checking
column presence on the first row was safe. JSON uploads can have rows
with different keys — a test upload where only the *second* row carried
`ground_truth_final_state` was reported as having no ground truth at all
(`ground_truth_present: false`), because the check only looked at
`valid_rows[0]`. Worse: had it been counted, a row missing both
`observed_status` and `ground_truth_final_state` would have compared
`None == None` and been silently scored "correct," inflating accuracy.

**How it was found:** Deliberately testing the JSON upload path with
intentionally heterogeneous rows — something the existing CSV-only tests
never exercised.

**Fix:** Ground-truth presence now checks across all rows, and accuracy
scoring only considers rows that actually have a ground-truth value —
locked in with `test_json_import_detects_ground_truth_across_all_rows`.

## 12. Unrecognized ground-truth value crashed the shared Prediction vs Reality endpoint

**What broke — this one is serious:** a user-uploaded CSV/JSON with any
value in `ground_truth_final_state` outside `SUCCESS`/`FAILED`/`PENDING`/
`CAPTURED`/`UNKNOWN` (a realistic typo — "PAID_LATE" instead of
"SUCCESS") would flow straight into the confusion-matrix aggregation and
crash `/api/experiments/prediction-vs-reality` with an unhandled
`KeyError`. Because this endpoint aggregates across *every* payment in
the database, not just the uploader's own data, one bad row from any
single user would have broken the Prediction vs Reality view for
everyone, until that row was manually removed from the database.

**How it was found:** Deliberately testing the CSV import path with a
plausible but not-quite-right ground-truth value — the kind of input a
real user would actually type, not a contrived attack string. Reproduced
the exact crash and traceback before writing any fix.

**Fix:** Two layers, not one. `prediction_evaluation.evaluate()` now
only produces a `Verdict` for actual-state values that map to a
recognized class — an unrecognized value is treated the same as "not yet
resolved" (returns `None`, excluded from evaluation) rather than passed
through as a fake label. `aggregate()` also independently guards against
any unrecognized class reaching the confusion matrix, so the aggregation
function itself can never crash regardless of what calls it in the
future — defense in depth, not reliance on a single upstream filter.
Verified the fix doesn't just avoid the crash but still correctly scores
valid data submitted afterward.

## 13. Zero-payment generation crashed, then silently misled after the crash was fixed

**What broke:** `--payments 0` crashed the generator with a
`ZeroDivisionError` computing percentage summaries. After fixing the
crash to exit cleanly instead, a *second*, subtler problem surfaced:
`POST /api/simulation/generate?payments=0` would return `200 ok` with
`"payments_loaded": 1500` — because the generator (correctly) left
`data/demo/*.csv` untouched when asked for zero payments, but the
endpoint then loaded whatever stale data was already sitting there from
a previous run and reported it as if it satisfied this request.

**How it was found:** Testing the boundary condition directly (something
no normal usage flow would exercise, which is exactly why it needed a
deliberate test) — first hit the crash, then, after fixing only the
crash, noticed the misleading success response on the very next test.

**Fix:** Two separate things, not one. The generator script now exits
cleanly and honestly on zero payments (no crash, no misleading writes).
Separately, the API endpoint now validates `payments >= 1` and
`sim_days >= 1` upfront and returns `400` with a clear message — so a
degenerate request is rejected outright rather than quietly substituted
with unrelated old data.

## 14. Incident detector CLI crashed on an empty dataset directory

**What broke:** `ml/pipeline/incident_detector.py`, run standalone
against an empty or missing `payments.csv`, crashed twice in sequence:
first `pd.date_range(NaT, NaT, ...)` inside `build_minutely_health`
(pandas can't build a range from two undefined timestamps), and — after
fixing that — a second crash in `IsolationForest.fit()`, which requires
at least one sample and got zero.

**How it was found:** Deliberately testing every data-processing
function against degenerate input (empty dataframes), not just the
happy-path dataset this repo ships with — the same discipline applied
throughout this log, extended to a module that hadn't been stress-tested
this way yet.

**Fix:** `build_minutely_health` now returns a correctly-shaped empty
dataframe instead of crashing; `isolation_forest_detector` short-circuits
to an empty result set instead of calling `fit()` on zero samples. Both
detectors and `evaluate_detector` were then re-verified together against
the empty case (zeroed-out precision/recall, not an exception) and the
full CLI script was run end-to-end against an empty directory — exits
cleanly, code 0 — before also re-confirming the normal, non-empty case
still produces its usual real results.

## 15. Webhook endpoint crashed on a valid-JSON-but-wrong-shape body

**What broke — the most security-relevant bug in this log:** the
webhook endpoint validates the HMAC signature and parses the body as
JSON, but never checked that the parsed result was actually a JSON
*object*. A body like `[1, 2, 3]` — valid JSON, wrong shape — passed
both checks and then crashed `normalize_webhook_payload()` with an
unhandled `AttributeError`, because it unconditionally called `.get()`
on whatever `json.loads()` returned.

**How it was found:** Deliberately testing malformed-but-technically-
valid inputs against a public-facing endpoint, which is exactly the kind
of input a public endpoint needs to survive regardless of source —
whether from a Razorpay platform quirk, a proxy rewriting the body, or
simply a malformed test request.

**Fix:** Added an explicit `isinstance(payload, dict)` check immediately
after parsing, before the payload reaches any application code — rejects
cleanly with `400`.

## 16. The same class of bug, one level deeper in the payload structure

**What broke:** Fixing #15 wasn't enough. A body that *is* a valid JSON
object at the top level, but whose nested `payload` field is a string
instead of an object (`{"event": "x", "payload": "oops"}`), still
crashed — `normalize_webhook_payload()` assumed every level of nesting
was a dict via chained `.get()` calls, and the second level wasn't
checked either.

**How it was found:** After fixing #15, immediately tested one level
deeper instead of assuming the fix was complete — the same discipline
that caught #15 in the first place, applied again rather than declared
"done."

**Fix:** Every nested `.get()` in `normalize_webhook_payload` now goes
through a `_safe_dict()` helper that defaults to `{}` for any
non-dict value, at every level, not just the top one. Re-verified three
cases together: the malformed nested shape (now degrades to `None`
fields instead of crashing), a completely empty payload, and a normal
valid Razorpay-shaped payload (still extracts every field correctly) —
confirming the fix didn't just stop the crash but preserved correct
behavior for real data.

## 17. `alembic` listed as a dependency but never actually configured

**What broke — not a crash, a false claim:** `requirements.txt` listed
`alembic` (implying real, versioned database migrations), but no
`alembic.ini` or migrations folder existed anywhere in the repo. The app
only ever used `Base.metadata.create_all()`. A dependency that implies
functionality the repo doesn't actually have is exactly the kind of
mismatch a careful reviewer would catch — better to catch it first.

**How it was found:** A deliberate audit specifically comparing every
listed dependency against what the code actually uses — the same check
that had already found `recharts` as unused dead weight earlier.

**Fix:** Removed `alembic` from `requirements.txt` rather than build out
migration tooling this project doesn't need — SQLite/Postgres
`create_all()` already covers the actual requirement (a fresh schema on
first run), and adding unused complexity would cut against the explicit
goal of keeping this repo simple.

## 18. CORS configured with a combination browsers silently reject

**What broke — not a crash, a dead configuration:** `allow_origins=["*"]`
was paired with `allow_credentials=True`. Per the CORS spec, browsers
refuse to honor credentialed requests with a wildcard origin — a server
can't say "any origin" and "trust my cookies" at the same time. This
app never actually sends credentialed requests, so `allow_credentials=True`
was silently doing nothing, which is its own kind of bug: config that
implies a capability (cross-origin cookies/auth) the app doesn't have
and can't use as configured.

**How it was found:** Deliberately auditing every middleware/dependency
setting against what it actually does — the same check that had already
caught the unused `recharts` dependency and the unconfigured `alembic`
entry.

**Fix:** Removed `allow_credentials=True`. This app has no cookie-based
auth, so it wasn't needed — simpler and no longer claims a capability
that was never functional.

## Why this file exists

Every fix above followed the same pattern: **run the actual system
end-to-end, don't assume correctness from reading code** — then when
something breaks, say exactly what broke, why, and what changed. That
discipline is what this log is meant to demonstrate, not just claim.
