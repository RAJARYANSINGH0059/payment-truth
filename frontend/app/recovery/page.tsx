"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import type { RecoveryRunResult, RecoverySummary } from "@/lib/api";
import ProvenanceBadge from "@/components/ProvenanceBadge";

function money(v: number | null | undefined) {
  return `₹${(v ?? 0).toLocaleString("en-IN")}`;
}

const STATUS_STYLE: Record<string, string> = {
  EXECUTED: "text-green-400",
  ESCALATED: "text-amber-400",
  BLOCKED_STOPPING_RULE: "text-white/50",
  SKIPPED_BATCH_CAP: "text-white/50",
};

export default function RecoveryPage() {
  const [summary, setSummary] = useState<RecoverySummary | null>(null);
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<RecoveryRunResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function loadSummary() {
    try {
      setSummary(await api.recoverySummary());
    } catch {
      setSummary(null);
    }
  }

  useEffect(() => {
    loadSummary();
  }, []);

  async function run() {
    setRunning(true);
    setError(null);
    setResult(null);
    try {
      const res = await api.runRecoveryBatch();
      setResult(res);
      await loadSummary();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Recovery</h1>
        <p className="text-white/50 text-sm">
          The ACT step: executes a bounded recovery action on every payment the decision
          engine has labelled RECOVER — never open-ended. Every action is either executed,
          escalated for compliant human/merchant review, or blocked by a stopping rule
          (retry cap / batch exposure cap), and every action is audit-logged.
        </p>
      </div>

      <div className="rounded-lg border border-white/10 p-4">
        <button
          onClick={run}
          disabled={running}
          className="rounded bg-blue-600 px-4 py-2 text-sm font-medium hover:bg-blue-500 disabled:opacity-50"
        >
          {running ? "Running batch…" : "RUN RECOVERY BATCH"}
        </button>
        <p className="text-xs text-white/40 mt-2">
          Runs once, on demand — safe to click repeatedly; already-resolved payments are
          never acted on twice (idempotency guardrail).
        </p>
        {error && <div className="text-sm text-red-400 mt-2">{error}</div>}
      </div>

      {summary && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
          <Stat label="Executed (all-time)" value={String(summary.executed)} />
          <Stat label="Escalated (pending review)" value={String(summary.escalated)} />
          <Stat label="Blocked by stopping rule" value={String(summary.blocked_stopping_rule)} />
          <Stat
            label="Measured Recovered"
            value={money(
              Object.values(summary.measured_recovered_value_by_basis).reduce((a, b) => a + b, 0)
            )}
            sub={
              <div className="mt-1 flex flex-wrap gap-1">
                {Object.keys(summary.measured_recovered_value_by_basis).map((basis) => (
                  <ProvenanceBadge key={basis} label={basis} />
                ))}
              </div>
            }
          />
        </div>
      )}

      {result && (
        <div className="rounded-lg border border-white/10 p-4 space-y-3">
          <div className="text-sm font-medium">Batch {result.batch_id}</div>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3 text-sm">
            <div>Candidates: <span className="text-white/70">{result.candidates_considered}</span></div>
            <div>Executed: <span className="text-green-400">{result.executed}</span></div>
            <div>Escalated: <span className="text-amber-400">{result.escalated}</span></div>
            <div>Blocked (cap): <span className="text-white/50">{result.blocked_stopping_rule}</span></div>
            <div>Skipped (batch cap): <span className="text-white/50">{result.skipped_batch_cap}</span></div>
          </div>
          <div className="text-sm">
            Measured recovered this batch: <span className="font-semibold">{money(result.measured_recovered_value.value)}</span>{" "}
            <span className="text-white/40 text-xs">({result.measured_recovered_value.basis})</span>
          </div>
          {result.escalated_value > 0 && (
            <div className="text-sm text-amber-400">
              {money(result.escalated_value)} routed to merchant/compliance review, not auto-acted on.
            </div>
          )}

          <table className="w-full text-sm mt-2">
            <thead className="text-left text-white/50 text-xs uppercase">
              <tr>
                <th className="py-1 pr-2">Payment</th>
                <th className="py-1 pr-2">Status</th>
                <th className="py-1 pr-2">Action</th>
                <th className="py-1 pr-2">Value</th>
                <th className="py-1 pr-2">Recovered</th>
                <th className="py-1">Reason</th>
              </tr>
            </thead>
            <tbody>
              {result.actions.map((a) => (
                <tr key={a.action_id} className="border-t border-white/5">
                  <td className="py-1 pr-2 font-mono text-xs">{a.payment_id}</td>
                  <td className={`py-1 pr-2 ${STATUS_STYLE[a.status] ?? ""}`}>{a.status}</td>
                  <td className="py-1 pr-2 text-white/60">{a.action_type ?? "—"}</td>
                  <td className="py-1 pr-2">{money(a.txn_value)}</td>
                  <td className="py-1 pr-2">
                    {a.recovered_value != null ? money(a.recovered_value) : "—"}
                    {a.financial_basis && (
                      <span className="ml-1"><ProvenanceBadge label={a.financial_basis} /></span>
                    )}
                  </td>
                  <td className="py-1 text-white/40 text-xs">{a.reason}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p className="text-xs text-white/40">
        Guardrails: transactions ≥ ₹5,000 or below 55% model confidence are always escalated
        for review, never auto-executed. Each payment gets at most 2 recovery attempts, ever.
        Each batch commits at most ₹5,00,000 of transaction value — the rest waits for the
        next run. None of this is configurable from the UI on purpose — a bounded workflow
        stays bounded.
      </p>
    </div>
  );
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-white/10 p-4">
      <div className="text-xs uppercase tracking-wide text-white/50">{label}</div>
      <div className="text-2xl font-semibold mt-1">{value}</div>
      {sub}
    </div>
  );
}
