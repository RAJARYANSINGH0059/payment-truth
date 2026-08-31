import Link from "next/link";
import { api } from "@/lib/api";
import ProvenanceBadge from "@/components/ProvenanceBadge";

const STATUS_COLOR: Record<string, string> = {
  SUCCESS: "text-green-400",
  FAILED: "text-red-400",
  PENDING: "text-amber-400",
  UNKNOWN: "text-white/50",
};

export default async function PaymentsPage() {
  const payments = await api.payments(100).catch(() => []);

  return (
    <div className="space-y-4">
      <div>
        <h1 className="text-xl font-semibold">Payments</h1>
        <p className="text-white/50 text-sm">Observed status is what the system currently knows — not necessarily the final truth.</p>
      </div>

      {payments.length === 0 && (
        <div className="text-white/50 text-sm">
          No payments yet. Generate synthetic data from the Simulation page, or send a test
          payment from the Razorpay Test page.
        </div>
      )}

      <div className="rounded-lg border border-white/10 overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-white/5 text-white/50 text-left">
            <tr>
              <th className="p-3">Payment ID</th>
              <th className="p-3">Amount</th>
              <th className="p-3">Method</th>
              <th className="p-3">Bank</th>
              <th className="p-3">Observed Status</th>
              <th className="p-3">Source</th>
            </tr>
          </thead>
          <tbody>
            {payments.map((p) => (
              <tr key={p.payment_id} className="border-t border-white/5 hover:bg-white/5">
                <td className="p-3">
                  <Link href={`/payments/${p.payment_id}`} className="text-blue-300 hover:underline">
                    {p.payment_id}
                  </Link>
                </td>
                <td className="p-3">₹{p.amount?.toLocaleString("en-IN")}</td>
                <td className="p-3">{p.payment_method}</td>
                <td className="p-3">{p.bank || "—"}</td>
                <td className={`p-3 font-medium ${STATUS_COLOR[p.observed_status] || ""}`}>{p.observed_status}</td>
                <td className="p-3"><ProvenanceBadge label={p.source} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
