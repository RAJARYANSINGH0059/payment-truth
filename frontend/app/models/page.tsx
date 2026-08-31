import { api } from "@/lib/api";

export default async function ModelsPage() {
  const metrics = await api.modelsMetrics().catch(() => null);

  if (!metrics) {
    return <div className="text-white/70">Couldn&apos;t reach the API.</div>;
  }

  const pm = metrics.payment_state_model as any;
  const id = metrics.incident_detector as any;

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">Models &amp; Metrics</h1>
        <p className="text-white/50 text-sm">
          All numbers below come from ml/artifacts/metrics.json — nothing here is hardcoded.
        </p>
      </div>

      <section className="rounded-lg border border-white/10 p-4">
        <h2 className="font-semibold mb-2">Payment State Predictor</h2>
        {pm?.models ? (
          <table className="w-full text-sm">
            <thead className="text-white/50 text-left">
              <tr><th className="py-1">Model</th><th>Macro F1</th></tr>
            </thead>
            <tbody>
              {Object.entries(pm.models).map(([name, m]: [string, any]) => (
                <tr key={name} className="border-t border-white/5">
                  <td className="py-1">{name}</td>
                  <td>{m.macro_f1}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="text-white/50 text-sm">Not yet trained — run ml/pipeline/train.py.</div>
        )}
        {pm?.beats_baseline !== undefined && (
          <div className="mt-2 text-sm">
            Beats baseline: <span className={pm.beats_baseline ? "text-green-400" : "text-red-400"}>
              {String(pm.beats_baseline)}
            </span>
          </div>
        )}
        {pm?.shap_top_features && (
          <div className="mt-3 text-sm">
            <div className="text-white/50 text-xs mb-1">Top SHAP features</div>
            {pm.shap_top_features.slice(0, 5).map((f: any) => (
              <div key={f.feature}>{f.feature}: {f.mean_abs_shap}</div>
            ))}
          </div>
        )}
      </section>

      <section className="rounded-lg border border-white/10 p-4">
        <h2 className="font-semibold mb-2">Incident Detector</h2>
        {id?.rule_baseline ? (
          <table className="w-full text-sm">
            <thead className="text-white/50 text-left">
              <tr><th className="py-1">Detector</th><th>Precision</th><th>Recall</th><th>FPR</th><th>Lead time (min)</th></tr>
            </thead>
            <tbody>
              {[id.rule_baseline, id.isolation_forest].map((d: any) => (
                <tr key={d.name} className="border-t border-white/5">
                  <td className="py-1">{d.name}</td>
                  <td>{d.precision}</td>
                  <td>{d.recall}</td>
                  <td>{d.false_positive_rate}</td>
                  <td>{d.avg_detection_lead_time_minutes ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <div className="text-white/50 text-sm">Not yet evaluated — run ml/pipeline/incident_detector.py.</div>
        )}
      </section>
    </div>
  );
}
