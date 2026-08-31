import { api } from "@/lib/api";

export default async function SettingsPage() {
  const health = await api.health().catch(() => null);

  return (
    <div className="space-y-4 max-w-xl">
      <h1 className="text-xl font-semibold">Settings</h1>
      <div className="rounded-lg border border-white/10 p-4 text-sm space-y-1">
        <div>Backend status: {health?.status ?? "unreachable"}</div>
        <div>Database: {health?.database ?? "—"}</div>
        <div>ML model: {health?.ml_model ?? "—"}</div>
        <div>Razorpay: {health?.razorpay ?? "—"}</div>
      </div>
      <p className="text-xs text-white/40">
        Secrets (RAZORPAY_KEY_SECRET, RAZORPAY_WEBHOOK_SECRET, DATABASE_URL, LLM_API_KEY) are
        never shown here or anywhere in the UI — they live only in your deployment&apos;s
        environment variables.
      </p>
    </div>
  );
}
