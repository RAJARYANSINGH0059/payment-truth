import "./globals.css";
import Link from "next/link";
import type { ReactNode } from "react";

export const metadata = {
  title: "Payment Truth",
  description: "Know the payment truth before you act.",
};

const NAV = [
  { href: "/", label: "Overview" },
  { href: "/payments", label: "Payments" },
  { href: "/incidents", label: "Incidents" },
  { href: "/simulation", label: "Simulation" },
  { href: "/models", label: "Models" },
  { href: "/audit", label: "Audit" },
  { href: "/razorpay", label: "Razorpay Test" },
  { href: "/settings", label: "Settings" },
];

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="min-h-screen flex">
          <nav className="w-56 shrink-0 border-r border-white/10 p-4 space-y-1">
            <div className="text-lg font-semibold mb-4">
              Payment Truth
              <div className="text-xs font-normal text-white/50">Know the payment truth before you act.</div>
            </div>
            {NAV.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className="block rounded px-3 py-2 text-sm text-white/80 hover:bg-white/10 hover:text-white"
              >
                {item.label}
              </Link>
            ))}
          </nav>
          <main className="flex-1 p-8">{children}</main>
        </div>
      </body>
    </html>
  );
}
