import { api } from "@/lib/api";
import ProvenanceBadge from "@/components/ProvenanceBadge";

function Stat({ label, value, sub }: { label: string; value: string; sub?: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-white/10 p-4">
      <div className="text-xs uppercase tracking-wide text-white/50">{label}</div>
      <div className="text-2xl font-semibold mt-1">{value}</div>
      {sub}
    </div>
  );
}

export default async function OverviewPage() {
  const [overview, health] = await Promise.all([
    api.overview().catch(() => null),
    api.health().catch(() => null),
  ]);

  if (!overview) {
    return (
      <div className="text-white/70">
        Couldn&apos;t reach the Payment Truth API. Confirm the backend is running and
        <code className="mx-1 rounded bg-white/10 px-1">NEXT_PUBLIC_API_URL</code>
        points to it.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Overview</h1>
        <p className="text-white/50 text-sm">
          What is most likely true about payments right now, and what should you do about it.
        </p>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <Stat
          label="Payment Health"
          value={overview.payment_health_pct !== null ? `${overview.payment_health_pct}%` : "—"}
          sub={<div className="mt-1 text-xs text-white/40">of currently-known status, not final outcome</div>}
        />
        <Stat label="Uncertain Payments" value={String(overview.uncertain_payments)} />
        <Stat
          label="Revenue at Risk"
          value={`₹${overview.revenue_at_risk.value.toLocaleString("en-IN")}`}
          sub={<div className="mt-2"><ProvenanceBadge label={overview.revenue_at_risk.basis} /></div>}
        />
        <Stat
          label="Revenue Protected"
          value={`₹${overview.revenue_protected.value.toLocaleString("en-IN")}`}
          sub={<div className="mt-2"><ProvenanceBadge label={overview.revenue_protected.basis} /></div>}
        />
      </div>

      <div className="rounded-lg border border-white/10 p-4">
        <div className="text-sm text-white/70 mb-2">System status</div>
        <div className="flex gap-4 text-sm">
          <span>Simulation: <ProvenanceBadge label={health?.simulation === "available" ? "SIMULATION" : "unavailable"} /></span>
          <span>ML model: {health?.ml_model}</span>
          <span>Razorpay: {health?.razorpay}</span>
          <span>Active incidents: {overview.active_incidents}</span>
        </div>
      </div>

      <div className="text-sm text-white/50">
        Total payments observed: {overview.total_payments}
      </div>
    </div>
  );
}
