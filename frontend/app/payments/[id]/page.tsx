import { api } from "@/lib/api";
import ProvenanceBadge from "@/components/ProvenanceBadge";

export default async function PaymentDetailPage({ params }: { params: { id: string } }) {
  const payment = await api.payment(params.id).catch(() => null);

  if (!payment) {
    return <div className="text-white/70">Payment {params.id} not found.</div>;
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-xl font-semibold">{payment.payment_id}</h1>
        <div className="flex gap-2 mt-1">
          <ProvenanceBadge label={payment.source} />
          <span className="text-white/50 text-sm">{payment.payment_method} · {payment.bank || "—"}</span>
        </div>
      </div>

      <div className="grid grid-cols-3 gap-4">
        <div className="rounded-lg border border-white/10 p-4">
          <div className="text-xs text-white/50">Amount</div>
          <div className="text-lg font-semibold">₹{payment.amount?.toLocaleString("en-IN")}</div>
        </div>
        <div className="rounded-lg border border-white/10 p-4">
          <div className="text-xs text-white/50">Observed Status</div>
          <div className="text-lg font-semibold">{payment.observed_status}</div>
        </div>
        <div className="rounded-lg border border-white/10 p-4">
          <div className="text-xs text-white/50">True Final State</div>
          <div className="text-lg font-semibold">{payment.true_final_state || "not yet resolved"}</div>
        </div>
      </div>

      <div>
        <h2 className="text-sm font-semibold text-white/70 mb-2">Timeline</h2>
        {payment.timeline.length === 0 ? (
          <div className="text-white/50 text-sm">No predictions recorded yet for this payment.</div>
        ) : (
          <div className="space-y-2">
            {payment.timeline.map((t, i) => (
              <div key={i} className="rounded border border-white/10 p-3 text-sm">
                <div className="text-white/50 text-xs">{t.timestamp}</div>
                <div className="mt-1">
                  Prediction: <code className="text-xs">{JSON.stringify(t.prediction)}</code>
                </div>
                {t.recommendation && <div className="mt-1">Recommendation: {t.recommendation}</div>}
                {t.verdict && (
                  <div className={`mt-2 inline-block rounded px-2 py-0.5 text-xs font-medium ${
                    t.verdict.was_correct ? "bg-green-500/20 text-green-300" : "bg-red-500/20 text-red-300"
                  }`}>
                    {t.verdict.was_correct ? "✓ CORRECT" : "✗ INCORRECT"} — predicted {t.verdict.predicted_class},
                    actual {t.verdict.actual_class}
                    {t.verdict.probability_of_actual_class !== null &&
                      ` (${Math.round((t.verdict.probability_of_actual_class ?? 0) * 100)}% on actual class)`}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
