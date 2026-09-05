"use client";

import { useEffect, useState } from "react";
import Script from "next/script";
import { api } from "@/lib/api";

declare global {
  interface Window {
    Razorpay: new (options: Record<string, unknown>) => { open: () => void };
  }
}

type Status = { environment: string; api: string; webhook: string; key_id: string | null };

export default function RazorpayPage() {
  const [status, setStatus] = useState<Status | null>(null);
  const [scriptLoaded, setScriptLoaded] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [paying, setPaying] = useState(false);

  useEffect(() => {
    api.razorpayStatus().then(setStatus).catch(() => setStatus(null));
  }, []);

  async function payWithRazorpay() {
    setPaying(true);
    setMessage(null);
    try {
      const res = await api.createTestOrder();
      const order = (res as { order: { id: string; amount: number; currency: string } }).order;

      if (!status?.key_id) {
        setMessage("Razorpay isn't configured on the backend yet (RAZORPAY_KEY_ID/SECRET missing) — "
          + "order created, but the payment popup needs a public key ID to open.");
        return;
      }
      if (!scriptLoaded || !window.Razorpay) {
        setMessage("Razorpay's checkout script hasn't loaded yet — try again in a second.");
        return;
      }

      const rzp = new window.Razorpay({
        key: status.key_id,
        amount: order.amount,
        currency: order.currency,
        order_id: order.id,
        name: "Payment Truth — Demo Product",
        description: "Test Mode purchase (no real money)",
        // This handler fires client-side on success — useful for immediate UI
        // feedback, but it is NOT the authoritative source of truth. See the
        // note below: only the server-side webhook (validated with
        // RAZORPAY_WEBHOOK_SECRET) should be trusted to update payment state,
        // because a client-side callback can be spoofed, skipped by closing
        // the tab, or lost to a network blip.
        handler: function (response: { razorpay_payment_id: string; razorpay_order_id: string }) {
          setMessage(
            `Checkout completed client-side (payment_id: ${response.razorpay_payment_id}). ` +
            `Waiting for the server-side webhook to confirm — check the Payments page in a few seconds.`
          );
        },
        modal: {
          ondismiss: function () {
            setPaying(false);
          },
        },
        prefill: { name: "Test Customer", email: "test@example.com" },
        theme: { color: "#7c3aed" },
      });
      rzp.open();
    } catch (e) {
      setMessage(`Failed: ${(e as Error).message}`);
    } finally {
      setPaying(false);
    }
  }

  return (
    <div className="space-y-6 max-w-xl">
      <Script src="https://checkout.razorpay.com/v1/checkout.js" onLoad={() => setScriptLoaded(true)} />

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
          onClick={payWithRazorpay}
          disabled={paying}
          className="rounded bg-purple-600 px-4 py-2 text-sm font-medium hover:bg-purple-500 disabled:opacity-50"
        >
          {paying ? "Opening…" : "PAY WITH RAZORPAY TEST MODE"}
        </button>
        {message && (
          <div className="mt-3 text-xs whitespace-pre-wrap text-white/70 bg-black/30 rounded p-2">{message}</div>
        )}
        {status?.api === "connected" && (
          <p className="mt-3 text-xs text-white/40">
            Use Razorpay&apos;s official test card in the popup: card number 4111 1111 1111 1111,
            any future expiry, any CVV, any OTP.
          </p>
        )}
      </div>

      <p className="text-xs text-white/40">
        Requires RAZORPAY_KEY_ID / RAZORPAY_KEY_SECRET configured on the backend, and (to see the
        prediction/verification flow update automatically) a Test Mode webhook pointing at
        /api/webhooks/razorpay with RAZORPAY_WEBHOOK_SECRET set — see README.
      </p>
    </div>
  );
}
