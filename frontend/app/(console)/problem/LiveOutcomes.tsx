"use client";

import { Fact, pct, useSystemFacts } from "@/app/_components/LiveFacts";

/** "What good looks like", measured on this system right now (GET
 * /system/facts). Counts only claims the agent workflow actually ran, never
 * the seeded history. */
export function LiveOutcomes() {
  const { data: f, error } = useSystemFacts();
  const v = <T,>(get: (x: NonNullable<typeof f>) => T) => (f ? get(f) : error ? null : undefined);
  const o = f?.outcomes;

  const tiles: { value: React.ReactNode; label: string; note: React.ReactNode }[] = [
    {
      value: <Fact value={v((x) => (x.outcomes.median_processing_s != null ? `${x.outcomes.median_processing_s} s` : null))} />,
      label: "median time from PDF to decision",
      note: o && o.processing_samples === 0 ? "measured on every new claim: run one on Live Run" : <>over <Fact value={v((x) => x.outcomes.processing_samples)} /> timed claims</>,
    },
    {
      value: <Fact value={v((x) => pct(x.outcomes.auto_decided, x.outcomes.decided_claims))} />,
      label: "of claims decided without a human",
      note: <>
        <Fact value={v((x) => x.outcomes.auto_decided)} /> auto-paid, <Fact value={v((x) => x.outcomes.to_officer)} /> sent to an officer, of{" "}
        <Fact value={v((x) => x.outcomes.claims_run_by_agents)} /> claims the agents ran
      </>,
    },
    {
      value: <Fact value={v((x) => pct(x.outcomes.deductions_with_clause, x.outcomes.deductions))} />,
      label: "of deductions cite a policy clause",
      note: <><Fact value={v((x) => x.outcomes.deductions_with_clause)} /> of <Fact value={v((x) => x.outcomes.deductions)} /> deductions</>,
    },
    {
      value: <Fact value={v((x) => x.audit.entries)} />,
      label: "governed actions in the audit log",
      note: <>
        <Fact value={v((x) => x.audit.refused)} /> refused by policy · hash chain <Fact value={v((x) => (x.audit.intact ? "intact" : "BROKEN"))} />
      </>,
    },
    {
      value: "0",
      label: "claims rejected by AI alone",
      note: <>
        possible only with an officer decision (STATE-001): <Fact value={v((x) => x.audit.rejections_with_officer_decision)} /> officer rejections,{" "}
        <Fact value={v((x) => x.audit.ai_rejections_refused)} /> AI attempts refused
      </>,
    },
    {
      value: <Fact value={v((x) => `${x.harbor.scored}/${x.harbor.scenarios}`)} />,
      label: "Harbor scenarios scored",
      note: <>
        outcome <Fact value={v((x) => pct(Math.round((x.harbor.outcome_pass_rate ?? 0) * 100), 100))} />, governance{" "}
        <Fact value={v((x) => pct(Math.round((x.harbor.governance_pass_rate ?? 0) * 100), 100))} /> · <Fact value={v((x) => x.harbor.claim_checks_passed)} />/
        <Fact value={v((x) => x.harbor.claim_checks)} /> live claims verified
      </>,
    },
  ];

  return (
    <>
      <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
        {tiles.map((t) => (
          <div key={t.label} className="rounded-xl border border-border bg-card p-5 shadow-sm">
            <p className="text-3xl font-semibold tracking-tight text-card-foreground">{t.value}</p>
            <p className="mt-1 font-medium text-card-foreground">{t.label}</p>
            <p className="mt-0.5 text-xs text-muted-foreground">{t.note}</p>
          </div>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground">
        Measured live from this system (claims the agents actually ran, the audit log and Harbor), not targets.
        {o && ` The ${o.seeded_history_claims} seeded historical claims are excluded.`}
      </p>
    </>
  );
}
