import { api } from "@/lib/api";

export default async function AuditPage() {
  const logs = await api.audit().catch(() => []);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Audit Trail</h1>
        <p className="text-white/50 text-sm">Every prediction and recommendation the system has made, in order.</p>
      </div>

      {logs.length === 0 && <div className="text-white/50 text-sm">No audit entries yet.</div>}

      <div className="space-y-2">
        {logs.map((l, i) => (
          <div key={i} className="rounded border border-white/10 p-3 text-sm">
            <div className="flex justify-between text-white/50 text-xs">
              <span>{l.timestamp}</span>
              <span>{l.entity_type} · {l.entity_id}</span>
            </div>
            <div className="mt-1">
              Prediction: <code className="text-xs">{JSON.stringify(l.prediction)}</code>
            </div>
            {l.recommendation && <div>Recommendation: {l.recommendation}</div>}
            {l.model_version && <div className="text-xs text-white/40">model: {l.model_version}</div>}
          </div>
        ))}
      </div>
    </div>
  );
}
