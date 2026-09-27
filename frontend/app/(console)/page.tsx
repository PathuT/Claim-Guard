"use client";

import Link from "next/link";
import useSWR from "swr";
import { Icon } from "@/app/_components/Icon";
import { useSessionUser } from "@/app/_components/SessionContext";
import { type ClaimSummary, getComplianceSummary, getPayoutFreeze, getSuite, listClaims } from "@/lib/api";
import { ROLE_LABEL, type Role, canAccess, visibleNav } from "@/lib/auth/roles";
import { formatInr, humanizeStatus, statusStyle } from "@/lib/format";

const FLOW: { label: string; detail: string; kind: "input" | "guard" | "agent" | "engine" | "decision" }[] = [
  { label: "Hospital PDFs", detail: "untrusted input", kind: "input" },
  { label: "Injection guardrail", detail: "hidden-text scan", kind: "guard" },
  { label: "Intake agent", detail: "extracts the bill", kind: "agent" },
  { label: "Medical reviewer", detail: "ICD-10 finding", kind: "agent" },
  { label: "Settlement engine", detail: "exact payable, clause per ₹", kind: "engine" },
  { label: "Coverage agent", detail: "plain-language reason", kind: "agent" },
  { label: "Explanation guardrail", detail: "every ₹ verified", kind: "guard" },
  { label: "Fraud agent", detail: "pseudonymised data", kind: "agent" },
  { label: "Pay ≤ ₹50k or officer", detail: "governed decision", kind: "decision" },
];

const KIND: Record<string, { dot: string; chip: string; label: string }> = {
  input: { dot: "bg-destructive", chip: "border-destructive/30 bg-destructive/5", label: "Untrusted input" },
  guard: { dot: "bg-chart-2", chip: "border-chart-2/30 bg-chart-2/5", label: "Guardrail" },
  agent: { dot: "bg-chart-1", chip: "border-chart-1/30 bg-chart-1/5", label: "Agno agent (LLM)" },
  engine: { dot: "bg-success", chip: "border-success/30 bg-success/5", label: "Policy-as-code" },
  decision: { dot: "bg-warning", chip: "border-warning/40 bg-warning/5", label: "Money or a human" },
};

const PRIMARY_ACTION: Record<Role, { href: string; label: string; icon: string }> = {
  platform_admin: { href: "/live", label: "Start the live demo", icon: "play" },
  claims_officer: { href: "/officer", label: "Open the review queue", icon: "inbox" },
  compliance_officer: { href: "/compliance", label: "Open compliance", icon: "shield" },
  policyholder: { href: "/policyholder", label: "Submit a claim", icon: "upload" },
};

const DEMO_PATH = [
  { href: "/problem", title: "Business problem", text: "Three-week claims, and why AI needs guardrails" },
  { href: "/architecture", title: "Architecture", text: "The brief, what was built, what was added" },
  { href: "/live", title: "Live Run · Jyoti", text: "Clean claim, auto-paid ₹37,300, Harbor-verified" },
  { href: "/live", title: "Live Run · Rahul", text: "Poisoned PDF flagged; red-team replay blocked" },
  { href: "/compliance", title: "Kill switch", text: "Freeze automated payouts, watch GOV-004" },
  { href: "/officer", title: "Human in the loop", text: "Break-glass with a reason, then approve" },
  { href: "/live#evals", title: "Harbor", text: "Run S07 live; S01–S10 scoreboard" },
];

function greeting(): string {
  const hour = new Date().getHours();
  return hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
}

export default function Dashboard() {
  const user = useSessionUser();
  const role = user?.role ?? "policyholder";
  const isStaff = role !== "policyholder";

  const { data: claims, error: claimsError } = useSWR(isStaff ? "dash-claims" : null, () => listClaims({}), { refreshInterval: 20_000 });
  const { data: compliance } = useSWR(isStaff ? "dash-compliance" : null, getComplianceSummary, { refreshInterval: 20_000 });
  const { data: suite } = useSWR(isStaff ? "dash-suite" : null, getSuite, { refreshInterval: 30_000 });
  const { data: freeze } = useSWR(isStaff ? "dash-freeze" : null, getPayoutFreeze, { refreshInterval: 20_000 });

  const all = claims?.claims ?? [];
  const paid = all.filter((c) => c.status === "paid");
  const pending = all.filter((c) => c.status === "pending_human");
  const paidOut = paid.reduce((sum, c) => sum + (c.assessment?.payable_amount ?? 0), 0);
  const denied = compliance ? Object.values(compliance.denied_by_rule).reduce((a, b) => a + b, 0) : null;
  const action = PRIMARY_ACTION[role];
  const firstName = user?.name.split(" ")[0] ?? "there";

  return (
    <div className="flex flex-col gap-6">
      {/* Welcome */}
      <section className="brand-grid relative overflow-hidden rounded-2xl bg-sidebar p-6 text-sidebar-foreground shadow-sm sm:p-8">
        <div className="pointer-events-none absolute -right-20 -top-24 h-72 w-72 rounded-full bg-chart-1/35 blur-3xl" />
        <div className="relative flex flex-wrap items-end justify-between gap-6">
          <div className="max-w-2xl">
            <p className="text-xs font-semibold uppercase tracking-[0.14em] text-chart-1">{user ? ROLE_LABEL[user.role] : "Console"}</p>
            <h1 className="mt-2 text-2xl font-semibold tracking-tight sm:text-3xl">
              {greeting()}, {firstName}.
            </h1>
            <p className="mt-2 text-sm leading-relaxed text-sidebar-muted sm:text-base">
              {isStaff
                ? "Agno agents assess every reimbursement claim; Microsoft AGT checks every action, each agent gets a seconds-long credential per collection, and Harbor verifies the result."
                : "Paid the hospital yourself? Upload the bill and discharge summary and get a decision with every deduction explained."}
            </p>
            <div className="mt-5 flex flex-wrap gap-2">
              <Link href={action.href} className="inline-flex items-center gap-2 rounded-lg bg-chart-1 px-4 py-2 text-sm font-semibold text-white shadow-sm transition hover:opacity-95">
                <Icon name={action.icon} />
                {action.label}
              </Link>
              {canAccess(role, "/architecture") && (
                <Link href="/architecture" className="inline-flex items-center gap-2 rounded-lg border border-sidebar-border bg-sidebar-accent px-4 py-2 text-sm font-medium transition hover:bg-sidebar-accent/70">
                  <Icon name="layers" />
                  How it&apos;s built
                </Link>
              )}
            </div>
          </div>
          {isStaff && (
            <ul className="grid w-full max-w-sm gap-2 text-sm">
              <Health label="Agents & APIs" ok={!claimsError && claims !== undefined} value={claimsError ? "Offline" : claims ? "Online" : "Checking…"} />
              <Health label="Audit hash chain" ok={compliance?.integrity.valid === true} value={compliance ? (compliance.integrity.valid ? `Intact · ${compliance.integrity.total_entries} entries` : "BROKEN") : "…"} />
              <Health label="Automated payouts" ok={freeze ? !freeze.frozen : true} value={freeze ? (freeze.frozen ? "Frozen by compliance" : "Active") : "…"} />
              <Health
                label="Harbor evaluation"
                ok={suite ? suite.outcome_pass_rate === 1 && suite.governance_pass_rate === 1 : true}
                value={suite ? `${suite.scored}/${suite.rows.length} scored · ${pct(suite.outcome_pass_rate)} / ${pct(suite.governance_pass_rate)}` : "…"}
              />
            </ul>
          )}
        </div>
      </section>

      {/* KPIs */}
      {isStaff && (
        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-5">
          <Kpi icon="file" label="Claims on file" value={claims ? all.length.toLocaleString("en-IN") : "—"} sub="synthetic book of business" />
          <Kpi icon="check" label="Paid" value={claims ? paid.length.toLocaleString("en-IN") : "—"} sub={claims ? `${formatInr(paidOut)} paid out` : ""} tone="success" />
          <Kpi icon="inbox" label="Awaiting an officer" value={claims ? pending.length.toLocaleString("en-IN") : "—"} sub="T3: big, flagged or excluded" tone="warning" href={canAccess(role, "/officer") ? "/officer" : undefined} />
          <Kpi icon="shield" label="Governed actions" value={compliance ? compliance.stats.total_actions.toLocaleString("en-IN") : "—"} sub={denied != null ? `${denied} refused by policy` : ""} />
          <Kpi icon="cpu" label="Harbor pass rate" value={suite ? pct(suite.governance_pass_rate) : "—"} sub="governance evidence, S01–S10" tone="success" href={canAccess(role, "/live") ? "/live#evals" : undefined} />
        </section>
      )}

      {/* Flow + recent claims */}
      <section className={`grid gap-6 ${isStaff ? "xl:grid-cols-[1.35fr_1fr]" : ""}`}>
        <div className="rounded-xl border border-border bg-card p-5 shadow-sm">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="font-semibold text-card-foreground">How a claim flows</h2>
            <span className="text-xs text-muted-foreground">One Agno Workflow · every data access governed</span>
          </div>
          <ol className="mt-4 grid gap-2 sm:grid-cols-3">
            {FLOW.map((step, i) => (
              <li key={step.label} className={`relative rounded-lg border px-3 py-2.5 ${KIND[step.kind].chip}`}>
                <span className="flex items-center gap-2 text-[11px] font-medium text-muted-foreground">
                  <span className="font-mono">{String(i + 1).padStart(2, "0")}</span>
                  <span className={`h-1.5 w-1.5 rounded-full ${KIND[step.kind].dot}`} />
                </span>
                <span className="mt-1 block text-sm font-semibold text-card-foreground">{step.label}</span>
                <span className="block text-xs text-muted-foreground">{step.detail}</span>
              </li>
            ))}
          </ol>
          <div className="mt-4 flex flex-wrap gap-x-4 gap-y-1.5 text-[11px] text-muted-foreground">
            {Object.values(KIND).map((k) => (
              <span key={k.label} className="flex items-center gap-1.5">
                <span className={`h-2 w-2 rounded-full ${k.dot}`} /> {k.label}
              </span>
            ))}
          </div>
        </div>

        {isStaff && (
          <div className="rounded-xl border border-border bg-card p-5 shadow-sm">
            <div className="flex items-baseline justify-between gap-2">
              <h2 className="font-semibold text-card-foreground">Latest claims</h2>
              {canAccess(role, "/officer") && (
                <Link href="/officer" className="text-xs font-medium text-chart-1 hover:underline">
                  Review queue →
                </Link>
              )}
            </div>
            {claimsError && <p className="mt-4 text-sm text-destructive">Can&apos;t reach AgentOS. Is `npm run dev` running?</p>}
            {!claims && !claimsError && <SkeletonRows />}
            {claims && (
              <ul className="mt-3 divide-y divide-border">
                {all.slice(0, 7).map((claim) => (
                  <ClaimRow key={claim.claim_id} claim={claim} linkable={canAccess(role, "/pipeline")} />
                ))}
              </ul>
            )}
          </div>
        )}
      </section>

      {/* Demo path (admin) and workspaces */}
      {role === "platform_admin" && (
        <section className="rounded-xl border border-border bg-card p-5 shadow-sm">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h2 className="font-semibold text-card-foreground">Demo path</h2>
            <span className="text-xs text-muted-foreground">About 20 minutes · docs/demo-script.md</span>
          </div>
          <ol className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4 2xl:grid-cols-7">
            {DEMO_PATH.map((step, i) => (
              <li key={step.title}>
                <Link href={step.href} className="flex h-full flex-col rounded-lg border border-border p-3 transition hover:border-chart-1/50 hover:shadow-sm">
                  <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-primary text-[11px] font-semibold text-primary-foreground">{i + 1}</span>
                  <span className="mt-2 text-sm font-semibold text-card-foreground">{step.title}</span>
                  <span className="mt-0.5 text-xs text-muted-foreground">{step.text}</span>
                </Link>
              </li>
            ))}
          </ol>
        </section>
      )}

      <section>
        <h2 className="mb-3 text-sm font-semibold text-muted-foreground">Your workspaces</h2>
        <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          {visibleNav(role)
            .flatMap((s) => s.items)
            .filter((item) => item.href !== "/" && !item.external)
            .map((item) => (
              <Link key={item.href} href={item.href} className="group flex gap-3 rounded-xl border border-border bg-card p-4 shadow-sm transition hover:border-chart-1/50 hover:shadow">
                <span className="inline-flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-chart-1/10 text-chart-1">
                  <Icon name={item.icon} className="h-5 w-5" />
                </span>
                <span>
                  <span className="flex items-center gap-1 font-medium text-card-foreground">
                    {item.label}
                    <Icon name="arrowRight" className="h-3.5 w-3.5 opacity-0 transition group-hover:opacity-100" />
                  </span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">{item.description}</span>
                </span>
              </Link>
            ))}
        </div>
      </section>
    </div>
  );
}

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${Math.round(v * 100)}%`;
}

function Health({ label, ok, value }: { label: string; ok: boolean; value: string }) {
  return (
    <li className="flex items-center justify-between gap-3 rounded-lg border border-sidebar-border bg-sidebar-accent/60 px-3 py-2">
      <span className="flex items-center gap-2 text-sidebar-muted">
        <span className={`h-2 w-2 rounded-full ${ok ? "bg-success" : "bg-destructive"}`} />
        {label}
      </span>
      <span className="truncate text-right text-xs font-medium">{value}</span>
    </li>
  );
}

function Kpi({ icon, label, value, sub, tone, href }: { icon: string; label: string; value: string; sub?: string; tone?: "success" | "warning"; href?: string }) {
  const accent = tone === "success" ? "text-success bg-success/10" : tone === "warning" ? "text-warning bg-warning/10" : "text-chart-1 bg-chart-1/10";
  const body = (
    <>
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-muted-foreground">{label}</span>
        <span className={`inline-flex h-8 w-8 items-center justify-center rounded-lg ${accent}`}>
          <Icon name={icon} />
        </span>
      </div>
      <p className="mt-2 text-2xl font-semibold tabular-nums tracking-tight text-card-foreground">{value}</p>
      {sub && <p className="mt-0.5 truncate text-xs text-muted-foreground">{sub}</p>}
    </>
  );
  const cls = "rounded-xl border border-border bg-card p-4 shadow-sm";
  return href ? (
    <Link href={href} className={`${cls} transition hover:border-chart-1/50 hover:shadow`}>
      {body}
    </Link>
  ) : (
    <div className={cls}>{body}</div>
  );
}

function ClaimRow({ claim, linkable }: { claim: ClaimSummary; linkable: boolean }) {
  const amount = claim.assessment?.payable_amount;
  const content = (
    <div className="flex items-center gap-3 py-2.5">
      <div className="min-w-0 flex-1">
        <p className="truncate font-mono text-xs font-semibold text-card-foreground">{claim.claim_id}</p>
        <p className="truncate text-xs text-muted-foreground">{claim.stated_illness}</p>
      </div>
      <div className="text-right">
        <p className="text-sm font-medium tabular-nums text-card-foreground">{formatInr(amount ?? claim.claimed_amount)}</p>
        <p className="text-[10px] text-muted-foreground">{amount != null ? "payable" : "claimed"}</p>
      </div>
      <span className={`w-28 shrink-0 rounded-full px-2 py-0.5 text-center text-[11px] font-medium capitalize ${statusStyle(claim.status)}`}>{humanizeStatus(claim.status)}</span>
    </div>
  );
  return <li>{linkable ? <Link href={`/pipeline?claim=${encodeURIComponent(claim.claim_id)}`} className="block rounded-md px-1 hover:bg-secondary/60">{content}</Link> : content}</li>;
}

function SkeletonRows() {
  return (
    <ul className="mt-3 flex flex-col gap-3">
      {Array.from({ length: 5 }, (_, i) => (
        <li key={i} className="h-9 animate-pulse rounded-md bg-secondary" />
      ))}
    </ul>
  );
}
