const STYLES: Record<string, string> = {
  SIMULATION: "bg-blue-500/20 text-blue-300",
  SYNTHETIC: "bg-blue-500/20 text-blue-300",
  RAZORPAY_TEST: "bg-purple-500/20 text-purple-300",
  ESTIMATED: "bg-amber-500/20 text-amber-300",
  PREDICTED: "bg-amber-500/20 text-amber-300",
  VERIFIED: "bg-green-500/20 text-green-300",
  SIMULATED: "bg-blue-500/20 text-blue-300",
};

export default function ProvenanceBadge({ label }: { label: string }) {
  const style = STYLES[label] || "bg-white/10 text-white/70";
  return (
    <span className={`inline-block rounded px-2 py-0.5 text-xs font-medium ${style}`}>
      {label}
    </span>
  );
}
