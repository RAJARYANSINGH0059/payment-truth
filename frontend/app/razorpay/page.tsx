"use client";

import { useEffect, useState } from "react";
import { api } from "@/lib/api";

export default function RazorpayPage() {
  const [status, setStatus] = useState<{ environment: string; api: string; webhook: string } | null>(null);
  const [orderResult, setOrderResult] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    api.razorpayStatus().then(setStatus).catch(() => setStatus(null));
  }, []);

  async function createOrder() {
    setCreating(true);
    setOrderResult(null);
    try {
      const res = await api.createTestOrder();
      setOrderResult(JSON.stringify(res, null, 2));
    } catch (e) {
      setOrderResult(`Failed: ${(e as Error).message} — is RAZORPAY_KEY_ID/SECRET configured?`);
    } finally {
      setCreating(false);
    }
  }

  return (
    <div className="space-y-6 max-w-xl">
      <div>
        <h1 className="text-xl font-semibold">Razorpay Test Connection</h1>
        <p className="text-white/50 text-sm">TEST MODE only. Never processes real money.</p>
      </div>

      <div className="rounded-lg border border-white/10 p-4 space-y-1 text-sm">
        <div>Environment: <span className="font-medium">{status?.environment ?? "—"}</span></div>
        <div>API: <span className="font-medium">{status?.api ?? "—"}</span></div>
        <div>Webhook: <span className="font-medium">{status?.webhook ?? "—"}</span></div>
      </div>

      <div className="rounded-lg border border-white/10 p-4">
        <div className="font-medium mb-1">Demo Product</div>
        <div className="text-2xl font-semibold mb-3">₹999</div>
        <button
          onClick={createOrder}
          disabled={creating}
          className="rounded bg-purple-600 px-4 py-2 text-sm font-medium hover:bg-purple-500 disabled:opacity-50"
        >
          {creating ? "Creating…" : "PAY WITH RAZORPAY TEST MODE"}
        </button>
        {orderResult && (
          <pre className="mt-3 text-xs whitespace-pre-wrap text-white/70 bg-black/30 rounded p-2">{orderResult}</pre>
        )}
      </div>

      <p className="text-xs text-white/40">
        This creates a test order via the backend. To complete an actual Test Mode payment and see
        the webhook → prediction → verification flow, configure RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET
        and a Test Mode webhook pointing at /api/webhooks/razorpay (see README).
      </p>
    </div>
  );
}
