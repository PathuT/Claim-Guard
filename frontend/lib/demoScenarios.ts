/** The 10 real scenarios from docs/use-case.md §8, for the Console's
 * "demo scenarios" one-click picker (not a fabricated list — every claim_id
 * here is real seed data from data/synthetic/generators/claims.py, and the
 * expected outcome is what evals/harbor/tasks/<id>/task.toml itself asserts
 * against the real running backend). S07/S08 are excluded: they're
 * governance-probe attacks with no claim_id at all (see
 * evals/harbor/adapter's own task_type split), not something the
 * Policyholder submit-a-claim flow can demonstrate. */
export interface DemoScenario {
  id: string;
  claimId: string;
  label: string;
  description: string;
}

export const DEMO_SCENARIOS: DemoScenario[] = [
  { id: "S01", claimId: "CLM-2026-018833", label: "S01 — Happy path", description: "Priya, dengue, auto-approved and paid straight through" },
  { id: "S02", claimId: "CLM-2026-018834", label: "S02 — Room-rent cap", description: "Priya, room rent exceeds plan cap, routes to officer review" },
  { id: "S03", claimId: "CLM-2026-018835", label: "S03 — Waiting period", description: "Rahul, policy still in its 30-day waiting period, non-accident illness" },
  { id: "S04", claimId: "CLM-2026-018836", label: "S04 — Duplicate bill fraud", description: "Rahul, the same bill was already claimed under another policy" },
  { id: "S05", claimId: "CLM-2026-018838", label: "S05 — Amount mismatch", description: "Rahul claims ₹1,20,000; the real bill totals ₹42,000" },
  { id: "S06", claimId: "CLM-2026-018839", label: "S06 — Prompt injection", description: "A hidden instruction in the discharge summary tries to redirect a ₹4,50,000 payout — never executed" },
  { id: "S09", claimId: "CLM-2026-018840", label: "S09 — Missing document", description: "Priya, no discharge summary uploaded — stopped before any agent runs" },
  { id: "S10", claimId: "CLM-2026-018841", label: "S10 — Day-care + watchlist", description: "Rahul, short stay at a watchlisted hospital — two flags at once" },
];
