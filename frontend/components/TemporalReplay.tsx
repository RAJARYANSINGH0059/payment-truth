"use client";

import { useState } from "react";
import { api } from "@/lib/api";
import type { ReplayData } from "@/lib/api";

export default function TemporalReplay({ paymentId }: { paymentId: string }) {
  const [data, setData] = useState<ReplayData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [shown, setShown] = useState(false);

  async function run() {
    setShown(true);
    setLoading(true);
    setError(null);
    try {
      const result = await api.replay(paymentId);
      setData(result);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div>
      <button
        onClick={run}
        className="rounded bg-purple-600 px-4 py-2 text-sm font-medium hover:bg-purple-500"
      >
        ▶ REPLAY
      </button>

      {shown && loading && <div className="text-white/50 text-sm mt-3">Loading replay…</div>}
      {shown && error && (
        <div className="text-white/50 text-sm mt-3">
          {error.includes("404") ? "No replay data — this payment may predate the current dataset, "
            + "or came from a webhook/upload rather than the simulator." : `Failed: ${error}`}
        </div>
      )}

      {data && (
        <div className="mt-4 space-y-3">
          <TimelineStep label="TRUE WORLD" color="text-white/70">
            Created {data.true_world.created_at} · true final state:{" "}
            <span className="font-semibold">{data.true_world.final_true_state}</span>
          </TimelineStep>

          <Arrow />
          <TimelineStep label="EVENT GENERATED → DELIVERED" color="text-amber-300">
            <div className="space-y-1">
              {data.event_delivery_timeline.map((e, i) => (
                <div key={i} className="text-xs">
                  <span className="text-white/50">{e.event_time}</span> → received{" "}
                  <span className="text-white/50">{e.received_time}</span> — {e.event_type}
                  {e.duplicate && <span className="ml-2 text-purple-300">[DUPLICATE]</span>}
                  {e.out_of_order && <span className="ml-2 text-red-300">[OUT-OF-ORDER]</span>}
                </div>
              ))}
            </div>
          </TimelineStep>

          <Arrow />
          <TimelineStep label="OBSERVED STATE (what the merchant knew, over time)" color="text-blue-300">
            <div className="space-y-1">
              {data.observation_snapshots.map((s, i) => (
                <div key={i} className="text-xs">
                  T+{s.seconds_after_creation}s — observed:{" "}
                  <span className="font-medium">{s.observed_status}</span>{" "}
                  <span className="text-white/40">({s.events_known_at_this_point} events known)</span>
                </div>
              ))}
            </div>
          </TimelineStep>

          <Arrow />
          <TimelineStep label="GROUND TRUTH (only knowable in hindsight)" color="text-green-300">
            Final observed state: <span className="font-semibold">{data.ground_truth_revealed_later.final_observed_state}</span>
            <p className="text-xs text-white/40 mt-1">{data.ground_truth_revealed_later.note}</p>
          </TimelineStep>

          <Arrow />
          <TimelineStep label="EVALUATION" color={data.naive_last_known_status_vs_truth.matched ? "text-green-400" : "text-red-400"}>
            Last known status before resolution: {data.naive_last_known_status_vs_truth.last_known_before_resolution} ·
            Actual: {data.naive_last_known_status_vs_truth.actual_final_state} —{" "}
            <span className="font-semibold">
              {data.naive_last_known_status_vs_truth.matched === null ? "N/A"
                : data.naive_last_known_status_vs_truth.matched ? "✓ MATCHED" : "✗ DID NOT MATCH"}
            </span>
          </TimelineStep>
        </div>
      )}
    </div>
  );
}

function Arrow() {
  return <div className="text-center text-white/20 text-xs">↓</div>;
}

function TimelineStep({ label, color, children }: { label: string; color: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-white/10 p-3">
      <div className={`text-xs font-semibold uppercase tracking-wide mb-1 ${color}`}>{label}</div>
      <div className="text-sm text-white/80">{children}</div>
    </div>
  );
}
