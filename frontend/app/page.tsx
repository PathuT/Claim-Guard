import Link from "next/link";

const ROLES = [
  {
    href: "/policyholder",
    title: "Policyholder",
    description: "Submit a claim by claim_id, and track its status and payout breakdown.",
  },
  {
    href: "/officer",
    title: "Officer",
    description: "Review the T3 human-review queue: flags, clauses, medical notes, and record a decision.",
  },
  {
    href: "/compliance",
    title: "Compliance",
    description: "View the governance audit log — every allow/deny decision by rule_id, system-wide.",
  },
  {
    href: "/pipeline",
    title: "Agent Pipeline",
    description: "See all 5 agents' real outputs for one claim, and which steps are independently audited.",
  },
] as const;

export default function Home() {
  return (
    <div className="flex flex-1 flex-col gap-8">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">ClaimGuard Console</h1>
        <p className="mt-2 max-w-2xl text-sm text-muted-foreground">
          A governed, auditable multi-agent health-insurance claims system. Every claim below is
          assessed by real agents (intake, medical reviewer, coverage, fraud, payout) behind a
          governance layer that logs and can deny every tool call — see the Compliance view for
          that log directly.
        </p>
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        {ROLES.map((role) => (
          <Link
            key={role.href}
            href={role.href}
            className="flex flex-col gap-2 rounded-lg border border-border bg-card p-5 transition-colors hover:border-primary/40"
          >
            <span className="font-semibold text-card-foreground">{role.title}</span>
            <span className="text-sm text-muted-foreground">{role.description}</span>
          </Link>
        ))}
      </div>
    </div>
  );
}
