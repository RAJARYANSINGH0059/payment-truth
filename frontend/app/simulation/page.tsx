"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { ImportResult } from "@/lib/api";

const PRESETS = [
  { label: "Normal Day", payments: 2000, simDays: 3 },
  { label: "Dense Traffic (Incident Test)", payments: 5000, simDays: 1 },
  { label: "Large Batch", payments: 20000, simDays: 10 },
];

export default function SimulationPage() {
  const [paymentsCount, setPaymentsCount] = useState(2000);
  const [seed, setSeed] = useState(42);
  const [simDays, setSimDays] = useState(3);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  async function run() {
    setRunning(true);
    setResult(null);
    try {
      const res = await api.runSimulation(paymentsCount, seed, simDays);
      setResult(res.status === "ok"
        ? `Generated dataset (payments=${paymentsCount}, seed=${seed}, sim_days=${simDays}).`
        : `Generation failed — ${res.stderr_tail.slice(0, 400)}`);
    } catch (e) {
      setResult(`Request failed: ${(e as Error).message}`);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="space-y-6 max-w-xl">
      <div>
        <h1 className="text-xl font-semibold">Simulation</h1>
        <p className="text-white/50 text-sm">
          Runs entirely on the synthetic temporal simulator — no Razorpay credentials required.
        </p>
      </div>

      <div className="rounded-lg border border-white/10 p-4 space-y-3">
        <label className="block text-sm">
          Payments
          <input
            type="number" min={1} value={paymentsCount}
            onChange={(e) => setPaymentsCount(Math.max(1, Number(e.target.value)))}
            className="mt-1 w-full rounded bg-white/5 border border-white/10 px-2 py-1"
          />
        </label>
        <label className="block text-sm">
          Seed (reproducibility)
          <input
            type="number" value={seed}
            onChange={(e) => setSeed(Number(e.target.value))}
            className="mt-1 w-full rounded bg-white/5 border border-white/10 px-2 py-1"
          />
        </label>
        <label className="block text-sm">
          Simulated days (fewer days = denser traffic = clearer incident signal)
          <input
            type="number" min={1} value={simDays}
            onChange={(e) => setSimDays(Math.max(1, Number(e.target.value)))}
            className="mt-1 w-full rounded bg-white/5 border border-white/10 px-2 py-1"
          />
        </label>

        <div className="flex gap-2 flex-wrap">
          {PRESETS.map((p) => (
            <button
              key={p.label}
              onClick={() => { setPaymentsCount(p.payments); setSimDays(p.simDays); }}
              className="text-xs rounded bg-white/10 px-2 py-1 hover:bg-white/20"
            >
              {p.label}
            </button>
          ))}
        </div>

        <button
          onClick={run}
          disabled={running}
          className="rounded bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500 disabled:opacity-50"
        >
          {running ? "Generating…" : "GENERATE DATA"}
        </button>
      </div>

      {result && <div className="text-sm text-white/70 whitespace-pre-wrap">{result}</div>}

      <p className="text-xs text-white/40">
        The model retrains itself automatically in the background after each generation —
        no manual command needed. Check the <a href="/models" className="underline">Models</a> page
        a few seconds after generating to see updated metrics.
      </p>

      <DataImport />
    </div>
  );
}

function DataImport() {
  const [file, setFile] = useState<File | null>(null);
  const [uploading, setUploading] = useState(false);
  const [result, setResult] = useState<ImportResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function upload() {
    if (!file) return;
    setUploading(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.importDataset(file);
      setResult(res);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setUploading(false);
    }
  }

  return (
    <div className="rounded-lg border border-white/10 p-4 space-y-3 max-w-xl">
      <h2 className="font-semibold text-sm">Import your own dataset (CSV / JSON)</h2>
      <p className="text-xs text-white/50">
        Required columns: payment_id, amount, payment_method. Include ground_truth_final_state
        to also get an accuracy readout — otherwise it&apos;s prediction-only, never scored.
      </p>
      <input
        type="file" accept=".csv,.json"
        onChange={(e) => setFile(e.target.files?.[0] ?? null)}
        className="text-sm"
      />
      <button
        onClick={upload}
        disabled={!file || uploading}
        className="block rounded bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500 disabled:opacity-50"
      >
        {uploading ? "Importing…" : "Upload"}
      </button>

      {error && <div className="text-sm text-red-400">{error}</div>}

      {result && (
        <div className="text-sm space-y-1">
          <div>Rows imported: {result.rows_total}</div>
          <div>Payments recognized: {result.payments_recognized}</div>
          <div>Invalid rows: {result.invalid_rows}</div>
          {result.evaluation && (
            <div className="text-white/70">
              Accuracy (naive baseline, ground truth present): {result.evaluation.accuracy}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
