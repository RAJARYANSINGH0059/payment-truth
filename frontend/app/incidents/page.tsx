import Link from "next/link";
import { api } from "@/lib/api";
import ProvenanceBadge from "@/components/ProvenanceBadge";

const SEVERITY_COLOR: Record<string, string> = {
  HIGH: "text-red-400",
  MEDIUM: "text-amber-400",
  LOW: "text-white/60",
};

export default async function IncidentsPage() {
  const incidents = await api.incidents().catch(() => []);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Incidents</h1>
        <p className="text-white/50 text-sm">Root cause is inferred from evidence — never invented, always shown with its confidence.</p>
      </div>

      {incidents.length === 0 && (
        <div className="text-white/50 text-sm">No incidents detected yet.</div>
      )}

      <div className="space-y-3">
        {incidents.map((i) => (
          <Link
            key={i.incident_id}
            href={`/incidents/${i.incident_id}`}
            className="block rounded-lg border border-white/10 p-4 hover:bg-white/5"
          >
            <div className="flex justify-between items-center">
              <div>
                <div className={`font-semibold ${SEVERITY_COLOR[i.severity] || ""}`}>{i.severity}</div>
                <div className="text-sm text-white/70">{i.incident_id}</div>
              </div>
              <div className="text-right">
                <div className="text-sm">
                  {i.root_cause || "UNKNOWN"}{" "}
                  {i.root_cause_confidence !== null && (
                    <span className="text-white/50">({Math.round((i.root_cause_confidence || 0) * 100)}%)</span>
                  )}
                </div>
                {i.revenue_exposure !== null && (
                  <div className="text-sm mt-1">
                    ₹{i.revenue_exposure.toLocaleString("en-IN")}{" "}
                    {i.financial_basis && <ProvenanceBadge label={i.financial_basis} />}
                  </div>
                )}
              </div>
            </div>
          </Link>
        ))}
      </div>
    </div>
  );
}
