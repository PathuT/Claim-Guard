import type { Metadata } from "next";
import { BrandMark, Icon } from "@/app/_components/Icon";
import { LoginForm } from "./LoginForm";

export const metadata: Metadata = {
  title: "Sign in — ClaimGuard",
};

const PILLARS = [
  { icon: "cpu", title: "Agentic AI you can audit", text: "Agno agents read the documents, review the case and screen for fraud, inside one governed workflow." },
  { icon: "key", title: "Least privilege, by the second", text: "Every agent gets its own short-lived JWT for one collection, only when it needs data." },
  { icon: "shield", title: "Policy before every action", text: "Microsoft AGT checks every tool call; every decision lands in a hash-chained audit log." },
];

export default async function LoginPage({ searchParams }: PageProps<"/login">) {
  const params = await searchParams;
  const next = typeof params.next === "string" ? params.next : "";
  return (
    <div className="grid min-h-screen lg:grid-cols-[1.05fr_1fr]">
      <section className="brand-grid relative hidden overflow-hidden bg-sidebar text-sidebar-foreground lg:flex lg:flex-col lg:justify-between lg:p-12">
        <div className="pointer-events-none absolute -right-32 -top-32 h-96 w-96 rounded-full bg-chart-1/30 blur-3xl" />
        <div className="pointer-events-none absolute -bottom-40 -left-24 h-96 w-96 rounded-full bg-chart-3/20 blur-3xl" />
        <div className="relative flex items-center gap-3">
          <BrandMark className="h-10 w-10" />
          <div className="leading-tight">
            <p className="text-lg font-semibold tracking-tight">ClaimGuard</p>
            <p className="text-xs text-sidebar-muted">Kaveri Health Assurance · claims console</p>
          </div>
        </div>

        <div className="relative max-w-xl">
          <p className="text-xs font-semibold uppercase tracking-[0.16em] text-chart-1">Governed agentic AI</p>
          <h1 className="mt-3 text-4xl font-semibold leading-tight tracking-tight">
            Health claims decided by AI agents, governed like a bank.
          </h1>
          <p className="mt-4 text-base leading-relaxed text-sidebar-muted">
            From hospital PDF to payout in one governed run, and every step accounted for: who acted, with which credential, under
            which rule.
          </p>
          <ul className="mt-8 flex flex-col gap-5">
            {PILLARS.map((pillar) => (
              <li key={pillar.title} className="flex gap-4">
                <span className="mt-0.5 inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-sidebar-accent text-chart-1 ring-1 ring-sidebar-border">
                  <Icon name={pillar.icon} />
                </span>
                <span>
                  <span className="block font-medium">{pillar.title}</span>
                  <span className="mt-0.5 block text-sm text-sidebar-muted">{pillar.text}</span>
                </span>
              </li>
            ))}
          </ul>
        </div>

        <p className="relative text-xs text-sidebar-muted">
          Agno · Microsoft Agent Governance Toolkit · EdDSA JWT · Arize Phoenix · Harbor · synthetic data only
        </p>
      </section>

      <section className="flex items-center justify-center px-4 py-10 sm:px-8">
        <div className="w-full max-w-md">
          <div className="mb-8 flex items-center gap-3 lg:hidden">
            <BrandMark className="h-9 w-9" />
            <p className="text-lg font-semibold tracking-tight">ClaimGuard</p>
          </div>
          <h2 className="text-2xl font-semibold tracking-tight">Sign in</h2>
          <p className="mt-1 text-sm text-muted-foreground">Use your Kaveri Health account, or pick a demo account below.</p>
          <LoginForm next={next} />
        </div>
      </section>
    </div>
  );
}
