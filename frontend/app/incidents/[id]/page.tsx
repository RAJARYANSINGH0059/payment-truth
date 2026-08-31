import { api } from "@/lib/api";
import ProvenanceBadge from "@/components/ProvenanceBadge";

type IncidentDetail = {
  incident_id: string;
  severity: string;
  affected_bank: string | null;
  affected_method: string | null;
  root_cause: string | null;
  root_cause_confidence: number | null;
  supporting_evidence: string[] | null;
  contradicting_evidence: string[] | null;
  revenue_exposure: number | null;
  expected_recoverable_value: number | null;
  financial_basis: string | null;
  outcome: string | null;
  similar_incidents: Array<{
    incident_id: string;
    similarity_pct: number;
    matched_on: string[];
    recommended_action: string | null;
    actual_outcome: string | null;
    revenue_impact: number | null;
  }>;
};

export default async function IncidentDetailPage({ params }: { params: { id: string } }) {
  const incident = (await api.incident(params.id).catch(() => null)) as IncidentDetail | null;

  if (!incident) {
    return <div className="text-white/70">Incident {params.id} not found.</div>;
  }

  return (
    <div className="space-y-6 max-w-2xl">
      <div>
        <h1 className="text-xl font-semibold">{incident.incident_id}</h1>
        <div className="text-white/50 text-sm">Severity: {incident.severity}</div>
      </div>

      <div className="rounded-lg border border-white/10 p-4">
        <div className="text-sm text-white/50 mb-1">Likely Root Cause</div>
        <div className="text-lg font-semibold">{incident.root_cause || "UNKNOWN"}</div>
        {incident.root_cause_confidence !== null && (
          <div className="text-white/70 text-sm">Confidence: {Math.round((incident.root_cause_confidence || 0) * 100)}%</div>
        )}

        {incident.supporting_evidence && incident.supporting_evidence.length > 0 && (
          <div className="mt-3">
            <div className="text-xs text-white/50 mb-1">Supporting Evidence</div>
            <ul className="list-disc list-inside text-sm space-y-0.5">
              {incident.supporting_evidence.map((e, i) => <li key={i}>{e}</li>)}
            </ul>
          </div>
        )}
        {incident.contradicting_evidence && incident.contradicting_evidence.length > 0 && (
          <div className="mt-3">
            <div className="text-xs text-white/50 mb-1">Contradicting Evidence</div>
            <ul className="list-disc list-inside text-sm space-y-0.5 text-white/70">
              {incident.contradicting_evidence.map((e, i) => <li key={i}>{e}</li>)}
            </ul>
          </div>
        )}
      </div>

      {incident.revenue_exposure !== null && (
        <div className="rounded-lg border border-white/10 p-4 flex justify-between items-center">
          <div>
            <div className="text-xs text-white/50">Revenue at Risk</div>
            <div className="text-lg font-semibold">₹{incident.revenue_exposure.toLocaleString("en-IN")}</div>
          </div>
          {incident.financial_basis && <ProvenanceBadge label={incident.financial_basis} />}
        </div>
      )}

      {incident.outcome && (
        <div className="rounded-lg border border-white/10 p-4">
          <div className="text-xs text-white/50 mb-1">Outcome</div>
          <div className="text-sm">{incident.outcome}</div>
        </div>
      )}

      {incident.similar_incidents && incident.similar_incidents.length > 0 && (
        <div>
          <h2 className="text-sm font-semibold text-white/70 mb-2">Historical Similarity</h2>
          <p className="text-xs text-white/40 mb-2">
            Structured similarity across payment method, bank, root cause, failure rate and duration —
            not proven causation.
          </p>
          <div className="space-y-2">
            {incident.similar_incidents.map((s) => (
              <div key={s.incident_id} className="rounded border border-white/10 p-3 text-sm">
                <div className="flex justify-between">
                  <span className="font-medium">{s.incident_id}</span>
                  <span>{s.similarity_pct}% similar</span>
                </div>
                {s.matched_on.length > 0 && (
                  <div className="text-xs text-white/50 mt-1">Matched on: {s.matched_on.join(", ")}</div>
                )}
                <div className="text-xs mt-1">
                  {s.recommended_action && <span>Action taken: {s.recommended_action} · </span>}
                  {s.actual_outcome && <span>Outcome: {s.actual_outcome}</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
