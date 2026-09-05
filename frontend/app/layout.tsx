import "./globals.css";
import Link from "next/link";
import type { ReactNode } from "react";

export const metadata = {
  title: "Payment Truth",
  description: "Know the payment truth before you act.",
};

// Grouped to match how a judge/user actually moves through the product
// (spec's OBSERVE -> UNDERSTAND -> PREDICT -> ACT -> LEARN loop), not
// alphabetically or by when each page was built.
const NAV_SECTIONS = [
  {
    label: "UNDERSTAND",
    items: [
      { href: "/", label: "Overview" },
      { href: "/payments", label: "Payments" },
      { href: "/incidents", label: "Incidents" },
    ],
  },
  {
    label: "ACT",
    items: [{ href: "/recovery", label: "Recovery" }],
  },
  {
    label: "LEARN",
    items: [
      { href: "/experiments", label: "Experiments" },
      { href: "/models", label: "Models" },
      { href: "/audit", label: "Audit" },
    ],
  },
  {
    label: "DATA SOURCES",
    items: [
      { href: "/simulation", label: "Simulation" },
      { href: "/razorpay", label: "Razorpay Test" },
    ],
  },
  {
    label: "SYSTEM",
    items: [{ href: "/settings", label: "Settings" }],
  },
];

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body>
        <div className="min-h-screen flex">
          <nav className="w-56 shrink-0 border-r border-white/10 p-4 space-y-5">
            <div className="text-lg font-semibold">
              Payment Truth
              <div className="text-xs font-normal text-white/50">Know the payment truth before you act.</div>
            </div>
            {NAV_SECTIONS.map((section) => (
              <div key={section.label}>
                <div className="px-3 text-[10px] font-semibold tracking-wider text-white/30 mb-1">
                  {section.label}
                </div>
                <div className="space-y-1">
                  {section.items.map((item) => (
                    <Link
                      key={item.href}
                      href={item.href}
                      className="block rounded px-3 py-2 text-sm text-white/80 hover:bg-white/10 hover:text-white"
                    >
                      {item.label}
                    </Link>
                  ))}
                </div>
              </div>
            ))}
          </nav>
          <main className="flex-1 p-8">{children}</main>
        </div>
      </body>
    </html>
  );
}
