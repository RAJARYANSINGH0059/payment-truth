const API_URL =
  process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// FastAPI's HTTPException returns {"detail": "..."}.
// Show the actual backend error instead of only the HTTP status code.
async function extractErrorMessage(
  res: Response,
  path: string
): Promise<string> {
  try {
    const body = await res.json();

    if (body && typeof body.detail === "string") {
      return body.detail;
    }
  } catch {
    // Response body was not JSON.
  }

  return `API error ${res.status} on ${path}`;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error(await extractErrorMessage(res, path));
  }

  return res.json();
}

async function post<T>(
  path: string,
  body?: unknown
): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });

  if (!res.ok) {
    throw new Error(await extractErrorMessage(res, path));
  }

  return res.json();
}

// -----------------------------------------------------------------------------
// HEALTH
// -----------------------------------------------------------------------------

export type Health = {
  status: string;
  database: string;
  ml_model: string;
  simulation: string;
  razorpay: string;
};

// -----------------------------------------------------------------------------
// PAYMENTS
// -----------------------------------------------------------------------------

export type PaymentSummary = {
  payment_id: string;
  amount: number;
  payment_method: string;
  bank: string | null;
  observed_status: string;
  source: string;
  created_at: string | null;
};

export type PaymentDetail = PaymentSummary & {
  true_final_state: string | null;

  timeline: Array<{
    timestamp: string;
    prediction: Record<string, unknown>;
    recommendation: string | null;
    confidence: number | null;

    verdict: {
      predicted_class: string;
      actual_class: string;
      probability_of_actual_class: number | null;
      was_correct: boolean;
    } | null;
  }>;
};

// -----------------------------------------------------------------------------
// INCIDENTS
// -----------------------------------------------------------------------------

export type IncidentSummary = {
  incident_id: string;
  severity: string;
  root_cause: string | null;
  root_cause_confidence: number | null;
  revenue_exposure: number | null;
  expected_recoverable_value: number | null;
  financial_basis: string | null;
};

// -----------------------------------------------------------------------------
// MODEL METRICS
// -----------------------------------------------------------------------------

export type ModelMetrics = {
  payment_state_model: Record<string, unknown>;
  incident_detector: Record<string, unknown>;
  model_status: string;
};

// -----------------------------------------------------------------------------
// OVERVIEW
// -----------------------------------------------------------------------------

export type Overview = {
  payment_health_pct: number | null;
  total_payments: number;
  uncertain_payments: number;

  revenue_at_risk: {
    value: number;
    basis: string;
  };

  revenue_protected: {
    value: number;
    basis: string;
  };

  active_incidents: number;
};

// -----------------------------------------------------------------------------
// DATA IMPORT
// -----------------------------------------------------------------------------

export type ImportResult = {
  rows_total: number;
  payments_recognized: number;
  events_recognized: number;
  invalid_rows: number;

  invalid_details: Array<{
    row: number;
    problems: string[];
  }>;

  imported_new_payments: number;
  ground_truth_present: boolean;

  evaluation: {
    note: string;
    accuracy: number | null;
  } | null;
};

// -----------------------------------------------------------------------------
// PREDICTION VS REALITY
// -----------------------------------------------------------------------------

export type PredictionVsReality = {
  total_evaluated: number;
  correct: number;
  incorrect: number;
  accuracy: number | null;
  average_confidence: number | null;
  brier_score: number | null;

  confusion_matrix: {
    labels: string[];
    matrix: Record<string, Record<string, number>>;
  };

  sample_correct: Array<{
    predicted_class: string;
    actual_class: string;
    probability_of_actual_class: number | null;
  }>;

  sample_incorrect: Array<{
    predicted_class: string;
    actual_class: string;
    probability_of_actual_class: number | null;
  }>;
};

// -----------------------------------------------------------------------------
// RECOVERY
// -----------------------------------------------------------------------------
// These types mirror backend/app/routers/recovery.py and
// backend/app/recovery_engine.py exactly.

export type RecoveryAction = {
  action_id: string;
  payment_id: string;
  status: string;
  action_type: string | null;
  reason: string;
  txn_value: number | null;
  recovered_value: number | null;
  financial_basis: string | null;
};

export type RecoveryRunResult = {
  batch_id: string;

  candidates_considered: number;
  executed: number;
  escalated: number;
  blocked_stopping_rule: number;
  skipped_batch_cap: number;

  total_txn_value_considered: number;

  measured_recovered_value: {
    value: number;
    basis: string;
  };

  escalated_value: number;

  actions: RecoveryAction[];
};

export type RecoverySummary = {
  total_actions: number;

  executed: number;
  escalated: number;
  blocked_stopping_rule: number;
  skipped_batch_cap: number;

  measured_recovered_value_by_basis: Record<string, number>;

  escalated_value_pending_review: number;
};

// -----------------------------------------------------------------------------
// TEMPORAL REPLAY
// -----------------------------------------------------------------------------
// Mirrors backend/app/temporal_replay.py::build_replay exactly.

export type ReplayData = {
  payment_id: string;
  scenario: string | null;

  true_world: {
    created_at: string | null;
    resolved_at: string | null;
    final_true_state: string | null;
  };

  event_delivery_timeline: Array<{
    event_time: string;
    received_time: string;
    event_type: string;
    duplicate: boolean;
    out_of_order: boolean;
  }>;

  observation_snapshots: Array<{
    observation_at: string;
    seconds_after_creation: string | null;
    observed_status: string;
    events_known_at_this_point: string;
  }>;

  ground_truth_revealed_later: {
    final_observed_state: string | null;
    note: string;
  };

  naive_last_known_status_vs_truth: {
    last_known_before_resolution: string | null;
    actual_final_state: string | null;
    matched: boolean | null;
  };
};

// -----------------------------------------------------------------------------
// API
// -----------------------------------------------------------------------------

export const api = {
  // Health
  health: () => get<Health>("/health"),

  // Dashboard
  overview: () => get<Overview>("/api/overview"),

  // Prediction evaluation
  predictionVsReality: () =>
    get<PredictionVsReality>(
      "/api/experiments/prediction-vs-reality"
    ),

  // Experiments
  experimentUnseenIncident: () =>
    get<Record<string, unknown>>(
      "/api/experiments/unseen-incident"
    ),

  experimentMemory: () =>
    get<Record<string, unknown>>(
      "/api/experiments/memory"
    ),

  experimentRevenue: () =>
    get<Record<string, unknown>>(
      "/api/experiments/revenue"
    ),

  // LLM explanation
  explain: (payload: unknown) =>
    post<{
      explanation: string;
      source: string;
    }>("/api/explain", payload),

  // Dataset import
  importDataset: async (
    file: File
  ): Promise<ImportResult> => {
    const form = new FormData();

    form.append("file", file);

    const res = await fetch(
      `${API_URL}/api/data/import`,
      {
        method: "POST",
        body: form,
      }
    );

    if (!res.ok) {
      throw new Error(
        `Import failed (${res.status})`
      );
    }

    return res.json();
  },

  // Audit
  audit: () =>
    get<
      Array<{
        timestamp: string;
        entity_type: string;
        entity_id: string;

        prediction: Record<string, unknown>;

        confidence: number | null;
        recommendation: string | null;
        model_version: string | null;
      }>
    >("/api/audit"),

  // Simulation
  runSimulation: (
    paymentsCount: number,
    seed: number,
    simDays: number
  ) =>
    post<{
      status: string;
      stdout_tail: string;
      stderr_tail: string;
    }>(
      `/api/simulation/generate?payments=${paymentsCount}&seed=${seed}&sim_days=${simDays}`
    ),

  // Payments
  payments: (limit = 50) =>
    get<PaymentSummary[]>(
      `/api/payments?limit=${limit}`
    ),

  payment: (id: string) =>
    get<PaymentDetail>(
      `/api/payments/${id}`
    ),

  replay: (id: string) =>
    get<ReplayData>(
      `/api/payments/${id}/replay`
    ),

  // Incidents
  incidents: () =>
    get<IncidentSummary[]>(
      "/api/incidents"
    ),

  incident: (id: string) =>
    get(
      `/api/incidents/${id}`
    ),

  // Model metrics
  modelsMetrics: () =>
    get<ModelMetrics>(
      "/api/models/metrics"
    ),

  // Razorpay
  razorpayStatus: () =>
    get<{
      environment: string;
      api: string;
      webhook: string;
      key_id: string | null;
    }>("/api/razorpay/status"),

  createTestOrder: () =>
    post(
      "/api/razorpay/test-order"
    ),

  // ---------------------------------------------------------------------------
  // RECOVERY
  // ---------------------------------------------------------------------------

  recoverySummary: () =>
    get<RecoverySummary>(
      "/api/recovery/summary"
    ),

  runRecoveryBatch: () =>
    post<RecoveryRunResult>(
      "/api/recovery/run"
    ),
};
