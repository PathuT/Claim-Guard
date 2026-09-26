import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import Link from "next/link";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "ClaimGuard Console",
  description: "Governed, auditable multi-agent health-insurance claims console (M8).",
};

const NAV_LINKS = [
  { href: "/policyholder", label: "Policyholder" },
  { href: "/officer", label: "Officer" },
  { href: "/compliance", label: "Compliance" },
  { href: "/pipeline", label: "Agent Pipeline" },
] as const;

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col bg-slate-50 text-slate-900">
        <header className="border-b border-slate-200 bg-white">
          <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-4">
            <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
              <span className="inline-flex h-7 w-7 items-center justify-center rounded-md bg-slate-900 text-sm text-white">
                CG
              </span>
              ClaimGuard
            </Link>
            <nav className="flex gap-1 text-sm">
              {NAV_LINKS.map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  className="rounded-md px-3 py-1.5 font-medium text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900"
                >
                  {link.label}
                </Link>
              ))}
              <a
                href="http://localhost:6006"
                target="_blank"
                rel="noopener noreferrer"
                className="rounded-md px-3 py-1.5 font-medium text-slate-600 transition-colors hover:bg-slate-100 hover:text-slate-900"
                title="Real OpenTelemetry traces for every claim, one layer down from this Console"
              >
                Phoenix traces ↗
              </a>
            </nav>
          </div>
        </header>
        <main className="mx-auto flex w-full max-w-5xl flex-1 flex-col px-6 py-8">
          {children}
        </main>
        <footer className="border-t border-slate-200 bg-white py-4 text-center text-xs text-slate-400">
          No login system exists (agent-to-agent JWT only) — every role view here is an unauthenticated lookup by policy/claim ID, by design (see docs/plan.md M8).
        </footer>
      </body>
    </html>
  );
}
