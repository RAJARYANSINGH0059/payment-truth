const API_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

// FastAPI's HTTPException returns {"detail": "..."} — surfacing that
// message (when present) instead of just the status code gives the user
// the actual reason ("payments must be at least 1") rather than an
// opaque "API error 400 on /api/simulation/generate".
async function extractErrorMessage(res: Response, path: string): Promise<string> {
  try {
    const body = await res.json();
    if (body && typeof body.detail === "string") return body.detail;
  } catch {
    // response body wasn't JSON — fall through to the generic message
  }
  return `API error ${res.status} on ${path}`;
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, { cache: "no-store" });
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res, path));
  }
  return res.json();
}

async function post<T>(path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_URL}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body ? JSON.stringify(body) : undefined,
    cache: "no-store",
  });
  if (!res.ok) {
    throw new Error(await extractErrorMessage(res, path));
  }
  return res.json();
}

export type Health = {
  status: string;
  database: string;
  ml_model: string;
  simulation: string;
  razorpay: string;
};

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

export type IncidentSummary = {
  incident_id: string;
  severity: string;
  root_cause: string | null;
  root_cause_confidence: number | null;
  revenue_exposure: number | null;
  expected_recoverable_value: number | null;
  financial_basis: string | null;
};

export type ModelMetrics = {
  payment_state_model: Record<string, unknown>;
  incident_detector: Record<string, unknown>;
  model_status: string;
};

export type Overview = {
  payment_health_pct: number | null;
  total_payments: number;
  uncertain_payments: number;
  revenue_at_risk: { value: number; basis: string };
  revenue_protected: { value: number; basis: string };
  revenue_recovered: { value: number; basis: string };
  pending_escalations: number;
  active_incidents: number;
};

export type RecoveryAction = {
  action_id: string;
  batch_id: string;
  payment_id: string;
  attempt_number: number;
  decision: string | null;
  status: "EXECUTED" | "ESCALATED" | "BLOCKED_STOPPING_RULE" | "SKIPPED_BATCH_CAP";
  action_type: string | null;
  reason: string | null;
  txn_value: number | null;
  recovered_value: number | null;
  financial_basis: string | null;
  created_at: string | null;
  executed_at: string | null;
};

export type RecoveryRunResult = {
  batch_id: string;
  candidates_considered: number;
  executed: number;
  escalated: number;
  blocked_stopping_rule: number;
  skipped_batch_cap: number;
  total_txn_value_considered: number;
  measured_recovered_value: { value: number; basis: string };
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

export type ImportResult = {
  rows_total: number;
  payments_recognized: number;
  events_recognized: number;
  invalid_rows: number;
  invalid_details: Array<{ row: number; problems: string[] }>;
  imported_new_payments: number;
  ground_truth_present: boolean;
  evaluation: { note: string; accuracy: number | null } | null;
};

export type PredictionVsReality = {
  total_evaluated: number;
  correct: number;
  incorrect: number;
  accuracy: number | null;
  average_confidence: number | null;
  brier_score: number | null;
  confusion_matrix: { labels: string[]; matrix: Record<string, Record<string, number>> };
  sample_correct: Array<{ predicted_class: string; actual_class: string; probability_of_actual_class: number | null }>;
  sample_incorrect: Array<{ predicted_class: string; actual_class: string; probability_of_actual_class: number | null }>;
};

export const api = {
  health: () => get<Health>("/health"),
  overview: () => get<Overview>("/api/overview"),
  predictionVsReality: () => get<PredictionVsReality>("/api/experiments/prediction-vs-reality"),
  experimentUnseenIncident: () => get<Record<string, unknown>>("/api/experiments/unseen-incident"),
  experimentMemory: () => get<Record<string, unknown>>("/api/experiments/memory"),
  experimentRevenue: () => get<Record<string, unknown>>("/api/experiments/revenue"),
  explain: (payload: unknown) => post<{ explanation: string; source: string }>("/api/explain", payload),
  importDataset: async (file: File): Promise<ImportResult> => {
    const form = new FormData();
    form.append("file", file);
    const res = await fetch(`${API_URL}/api/data/import`, { method: "POST", body: form });
    if (!res.ok) throw new Error(`Import failed (${res.status})`);
    return res.json();
  },
  audit: () => get<Array<{
    timestamp: string; entity_type: string; entity_id: string;
    prediction: Record<string, unknown>; confidence: number | null;
    recommendation: string | null; model_version: string | null;
  }>>("/api/audit"),
  runSimulation: (paymentsCount: number, seed: number, simDays: number) =>
    post<{ status: string; stdout_tail: string; stderr_tail: string }>(
      `/api/simulation/generate?payments=${paymentsCount}&seed=${seed}&sim_days=${simDays}`
    ),
  payments: (limit = 50) => get<PaymentSummary[]>(`/api/payments?limit=${limit}`),
  payment: (id: string) => get<PaymentDetail>(`/api/payments/${id}`),
  incidents: () => get<IncidentSummary[]>("/api/incidents"),
  incident: (id: string) => get(`/api/incidents/${id}`),
  modelsMetrics: () => get<ModelMetrics>("/api/models/metrics"),
  razorpayStatus: () => get<{ environment: string; api: string; webhook: string; key_id: string | null }>("/api/razorpay/status"),
  createTestOrder: () => post("/api/razorpay/test-order"),
  runRecoveryBatch: (limit = 100) => post<RecoveryRunResult>(`/api/recovery/run?limit=${limit}`),
  recoveryActions: (limit = 100) => get<RecoveryAction[]>(`/api/recovery/actions?limit=${limit}`),
  recoverySummary: () => get<RecoverySummary>("/api/recovery/summary"),
};
