"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import ProvenanceBadge from "@/components/ProvenanceBadge";

type Tab = "prediction" | "unseen" | "memory" | "revenue";

const TABS: { id: Tab; label: string }[] = [
  { id: "prediction", label: "Prediction vs Reality" },
  { id: "unseen", label: "Unseen Incident" },
  { id: "memory", label: "Incident Memory" },
  { id: "revenue", label: "Revenue Protection" },
];

export default function ExperimentsPage() {
  const [tab, setTab] = useState<Tab>("prediction");
  const [data, setData] = useState<Record<string, unknown> | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setLoading(true);
    setError(null);
    const fetchers: Record<Tab, () => Promise<Record<string, unknown>>> = {
      prediction: () => api.predictionVsReality() as unknown as Promise<Record<string, unknown>>,
      unseen: api.experimentUnseenIncident,
      memory: api.experimentMemory,
      revenue: api.experimentRevenue,
    };
    fetchers[tab]()
      .then(setData)
      .catch((e) => setError((e as Error).message))
      .finally(() => setLoading(false));
  }, [tab]);

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Experiments</h1>
        <p className="text-white/50 text-sm">
          Every number below comes from an actual run of the corresponding script — nothing is hardcoded.
          If a card shows &quot;not yet run&quot;, run the script named to generate it.
        </p>
      </div>

      <div className="flex gap-2 border-b border-white/10">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={`px-3 py-2 text-sm border-b-2 -mb-px ${
              tab === t.id ? "border-blue-500 text-white" : "border-transparent text-white/50 hover:text-white/80"
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {loading && <div className="text-white/50 text-sm">Loading…</div>}
      {error && <div className="text-red-400 text-sm">Couldn&apos;t reach the API: {error}</div>}

      {!loading && !error && data && (
        <>
          {tab === "prediction" && <PredictionVsRealityView data={data as any} />}
          {tab === "unseen" && <UnseenIncidentView data={data as any} />}
          {tab === "memory" && <MemoryView data={data as any} />}
          {tab === "revenue" && <RevenueView data={data as any} />}
        </>
      )}
    </div>
  );
}

function NotYetRun({ howTo }: { howTo: string }) {
  return (
    <div className="rounded-lg border border-white/10 p-4 text-sm text-white/60">
      Not yet run. From the repo root: <code className="rounded bg-white/10 px-1">{howTo}</code>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/10 p-3">
      <div className="text-xs text-white/50">{label}</div>
      <div className="text-lg font-semibold">{value}</div>
    </div>
  );
}

function PredictionVsRealityView({ data }: { data: any }) {
  if (!data.total_evaluated) {
    return (
      <div className="text-sm text-white/60">
        No predictions have resolved to ground truth yet. Generate data from the Simulation page — once payments
        resolve, their predictions become evaluable here.
      </div>
    );
  }
  const labels: string[] = data.confusion_matrix.labels;
  const matrix = data.confusion_matrix.matrix;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Stat label="Evaluated" value={String(data.total_evaluated)} />
        <Stat label="Accuracy" value={`${Math.round((data.accuracy ?? 0) * 100)}%`} />
        <Stat label="Correct / Incorrect" value={`${data.correct} / ${data.incorrect}`} />
        <Stat label="Avg. Confidence" value={data.average_confidence !== null ? `${Math.round(data.average_confidence * 100)}%` : "—"} />
      </div>

      <div>
        <h2 className="text-sm font-semibold text-white/70 mb-2">Confusion Matrix (rows = predicted, cols = actual)</h2>
        <table className="text-sm border border-white/10">
          <thead>
            <tr>
              <th className="p-2 text-white/40"></th>
              {labels.map((l) => <th key={l} className="p-2 text-white/50">{l}</th>)}
            </tr>
          </thead>
          <tbody>
            {labels.map((row) => (
              <tr key={row} className="border-t border-white/10">
                <td className="p-2 text-white/50">{row}</td>
                {labels.map((col) => (
                  <td key={col} className="p-2 text-center">{matrix[row]?.[col] ?? 0}</td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {data.sample_correct?.[0] && (
          <div className="rounded-lg border border-green-500/30 p-3 text-sm">
            <div className="text-green-400 font-medium mb-1">✓ CORRECT example</div>
            <div>Predicted: {data.sample_correct[0].predicted_class}</div>
            <div>Actual: {data.sample_correct[0].actual_class}</div>
          </div>
        )}
        {data.sample_incorrect?.[0] && (
          <div className="rounded-lg border border-red-500/30 p-3 text-sm">
            <div className="text-red-400 font-medium mb-1">✗ INCORRECT example</div>
            <div>Predicted: {data.sample_incorrect[0].predicted_class}</div>
            <div>Actual: {data.sample_incorrect[0].actual_class}</div>
          </div>
        )}
      </div>
    </div>
  );
}

function UnseenIncidentView({ data }: { data: any }) {
  if (data.status === "not yet run") return <NotYetRun howTo={data.how_to_run} />;
  const known = data.known_configuration, unseen = data.unseen_configuration;
  return (
    <div className="space-y-4">
      <p className="text-xs text-white/50">
        Trained on <ProvenanceBadge label="SYNTHETIC" /> data ({data.train_config.config}.yaml), tested on a
        deliberately different distribution ({data.test_config.config}.yaml) the model never saw during training.
      </p>
      <div className="grid grid-cols-3 gap-3">
        <Stat label="Known-config Macro F1" value={String(known.macro_f1)} />
        <Stat label="Unseen-config Macro F1" value={String(unseen.macro_f1)} />
        <Stat label="Generalization Gap" value={String(data.generalization_gap_macro_f1)} />
      </div>
      <div className="text-sm text-white/50">
        {data.n_train_fit} training rows, {data.n_known_holdout} known-config holdout rows,{" "}
        {data.n_unseen_test} unseen-config test rows.
      </div>
    </div>
  );
}

function MemoryView({ data }: { data: any }) {
  if (data.status === "not yet run") return <NotYetRun howTo={data.how_to_run} />;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div className="rounded-lg border border-white/10 p-4">
          <div className="font-medium mb-2">Without Memory</div>
          <div className="text-sm">Root-cause top-1: {Math.round((data.without_memory.root_cause_top1_accuracy ?? 0) * 100)}%</div>
          <div className="text-sm">Avg. confidence: {Math.round((data.without_memory.average_confidence ?? 0) * 100)}%</div>
        </div>
        <div className="rounded-lg border border-white/10 p-4">
          <div className="font-medium mb-2">With Memory</div>
          <div className="text-sm">Root-cause top-1: {Math.round((data.with_memory.root_cause_top1_accuracy ?? 0) * 100)}%</div>
          <div className="text-sm">Avg. confidence: {Math.round((data.with_memory.average_confidence ?? 0) * 100)}%</div>
        </div>
      </div>
      <div className="text-sm text-white/70">
        Accuracy change: {data.accuracy_improvement >= 0 ? "+" : ""}{Math.round(data.accuracy_improvement * 100)}pp ·
        Confidence change: {data.confidence_improvement >= 0 ? "+" : ""}{Math.round(data.confidence_improvement * 100)}pp
      </div>
      <p className="text-xs text-white/40">{data.note}</p>
      <p className="text-xs text-white/40">
        Based on {data.n_scored_incidents} of {data.n_incidents_total} incidents in this run
        ({data.skipped_systemic_no_category_match} excluded — no matching root-cause category to score against).
      </p>
    </div>
  );
}

function RevenueView({ data }: { data: any }) {
  if (data.status === "not yet run") return <NotYetRun howTo={data.how_to_run} />;
  const a = data.strategy_a_naive, b = data.strategy_b_payment_truth;
  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 gap-4">
        <div className="rounded-lg border border-white/10 p-4">
          <div className="font-medium mb-2">Naive Strategy</div>
          <p className="text-xs text-white/40 mb-2">{a.description}</p>
          <div className="text-sm">Wrong actions: {a.wrong_actions} (₹{a.wrong_action_value.toLocaleString("en-IN")})</div>
          <div className="text-sm">Unnecessary retries: {a.unnecessary_retries}</div>
          <div className="text-sm">Recovered value: ₹{a.recovered_value.toLocaleString("en-IN")}</div>
        </div>
        <div className="rounded-lg border border-white/10 p-4">
          <div className="font-medium mb-2">Payment Truth</div>
          <p className="text-xs text-white/40 mb-2">{b.description}</p>
          <div className="text-sm">Wrong actions: {b.wrong_actions} (₹{b.wrong_action_value.toLocaleString("en-IN")})</div>
          <div className="text-sm">Unnecessary retries: {b.unnecessary_retries}</div>
          <div className="text-sm">Recovered value: ₹{b.recovered_value.toLocaleString("en-IN")}</div>
        </div>
      </div>
      <div className="rounded-lg border border-white/10 p-4 text-sm">
        <div>Wrong actions reduced: {data.improvement.wrong_actions_reduced}</div>
        <div>Wrong-action value reduced: ₹{data.improvement.wrong_action_value_reduced.toLocaleString("en-IN")}</div>
      </div>
      <p className="text-xs text-white/40">{data.note}</p>
    </div>
  );
}
