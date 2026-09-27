import Link from "next/link";

const FLOW: { label: string; kind: "input" | "agent" | "code" | "guard" | "human" }[] = [
  { label: "Hospital PDFs (untrusted)", kind: "input" },
  { label: "Injection guardrail", kind: "guard" },
  { label: "Intake agent", kind: "agent" },
  { label: "Medical reviewer agent", kind: "agent" },
  { label: "Settlement (code)", kind: "code" },
  { label: "Coverage agent", kind: "agent" },
  { label: "Explanation guardrail", kind: "guard" },
  { label: "Fraud agent", kind: "agent" },
  { label: "Tier T2 / T3 (code)", kind: "code" },
  { label: "Governed payout — or a human officer", kind: "human" },
];

const KIND_STYLE: Record<string, string> = {
  input: "border-destructive/40 bg-destructive/5 text-destructive",
  agent: "border-chart-1/40 bg-chart-1/10 text-card-foreground",
  code: "border-success/40 bg-success/10 text-card-foreground",
  guard: "border-chart-2/50 bg-chart-2/10 text-card-foreground",
  human: "border-warning/50 bg-warning/10 text-card-foreground",
};

const START = [
  {
    href: "/architecture",
    step: "1",
    title: "Architecture",
    description: "The brief vs what was built and added, system and request-flow diagrams, the security model, design decisions and what we learned.",
  },
  {
    href: "/live",
    step: "2",
    title: "Live Run",
    description: "Upload real PDFs and watch the Agno Workflow assess the claim: every agent, LLM call, policy decision, token and gateway check, live.",
  },
];

const EXTRAS = [
  { href: "/live", title: "Prompt-injection guardrail", description: "Hidden instructions in a PDF are flagged before any agent runs. A flagged claim can never be auto-paid." },
  { href: "/live", title: "Anti-hallucination guardrail", description: "Every ₹ amount in the customer explanation is checked against the settlement, and replaced if it was invented." },
  { href: "/compliance", title: "Payout kill switch", description: "Compliance freezes automated payouts in one click. The toggle is governed and audited, and officer payouts still work." },
  { href: "/live", title: "Cost & token meter", description: "LLM calls, tokens, time in the model and governance decisions for every run, measured from the spans." },
];

const ROLES = [
  { href: "/policyholder", title: "Policyholder", description: "Submit a claim with the hospital PDFs; get a decision and a breakdown citing the policy clause for every deduction." },
  { href: "/officer", title: "Claims officer", description: "Decide the T3 queue: findings, fraud flags and clauses; audited break-glass for the discharge summary." },
  { href: "/compliance", title: "Compliance", description: "Payout kill switch (GOV-004), hash-chain integrity, denials by rule, activity by agent, break-glass use, and the full audit log." },
  { href: "/pipeline", title: "Agent pipeline", description: "Each workflow step's stored output for one claim, and which steps made governed, audited calls." },
];

export default function Home() {
  return (
    <div className="flex flex-1 flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">ClaimGuard</h1>
        <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
          Agentic AI for health-insurance reimbursement claims — built so that it can be trusted with medical records and money.
          Four Agno agents run inside one Agno Workflow; every action they take is checked by Microsoft AGT
          policy in code, every data access needs a short-lived single-scope JWT, every decision is in a hash-chained audit
          log and one Phoenix trace, and Harbor re-runs ten scenarios, attacks included, as automated evaluations.
        </p>
      </div>

      <section className="rounded-lg border border-border bg-card p-5">
        <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">How a claim flows</p>
        <ol className="mt-3 flex flex-wrap items-center gap-2 text-sm">
          {FLOW.map((node, i) => (
            <li key={node.label} className="flex items-center gap-2">
              <span className={`rounded-md border px-3 py-1.5 font-medium ${KIND_STYLE[node.kind]}`}>{node.label}</span>
              {i < FLOW.length - 1 && <span className="text-muted-foreground">→</span>}
            </li>
          ))}
        </ol>
        <p className="mt-3 text-xs text-muted-foreground">
          Blue = Agno agent (LLM) · green = policy-as-code (exact maths and routing) · orange = guardrail (code) · amber = money or a human decision. Every data access and
          state change on the way passes governance → token service → data gateway.
        </p>
      </section>

      <section>
        <p className="mb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">Added beyond the brief</p>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {EXTRAS.map((x) => (
            <Link key={x.title} href={x.href} className="rounded-lg border border-border bg-card p-4 transition-colors hover:border-primary/40">
              <span className="text-sm font-semibold text-card-foreground">{x.title}</span>
              <span className="mt-1 block text-xs text-muted-foreground">{x.description}</span>
            </Link>
          ))}
        </div>
      </section>

      <div className="grid gap-4 md:grid-cols-2">
        {START.map((s) => (
          <Link key={s.href} href={s.href} className="flex gap-4 rounded-lg border border-primary/30 bg-card p-5 transition-colors hover:border-primary">
            <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary text-sm font-semibold text-primary-foreground">{s.step}</span>
            <span>
              <span className="font-semibold text-card-foreground">{s.title}</span>
              <span className="mt-1 block text-sm text-muted-foreground">{s.description}</span>
            </span>
          </Link>
        ))}
      </div>

      <div>
        <p className="mb-3 text-xs font-medium uppercase tracking-wide text-muted-foreground">Role views</p>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {ROLES.map((role) => (
            <Link key={role.href} href={role.href} className="flex flex-col gap-2 rounded-lg border border-border bg-card p-5 transition-colors hover:border-primary/40">
              <span className="font-semibold text-card-foreground">{role.title}</span>
              <span className="text-sm text-muted-foreground">{role.description}</span>
            </Link>
          ))}
        </div>
      </div>
    </div>
  );
}
