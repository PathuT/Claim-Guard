"use client";

import type { ClaimEvaluation, ClaimEvaluationCheck } from "@/lib/api";

/** Harbor's verdict on the claim that has just run: the per-claim check
 * the Live Run page starts automatically (backend/api/claim_evaluation.py,
 * evals/harbor/run_claim_eval.py). Same verifier as the S01–S10 suite,
 * scoring outcome and governance evidence. */
export function ClaimEvaluationCard({ evaluation, starting }: { evaluation: ClaimEvaluation | null; starting: boolean }) {
  const running = starting || evaluation?.status === "running";
  const done = evaluation?.status === "done";
  const passed = done && evaluation.outcome === 1 && evaluation.governance === 1;
  const border = running ? "border-chart-1/40" : !done ? "border-border" : passed ? "border-success/50" : "border-destructive/50";

  return (
    <section className={`rounded-lg border-2 bg-card p-4 ${border}`}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Automated evaluation · Harbor</p>
          <p className="font-semibold text-card-foreground">
            {running ? "Harbor is checking this claim…" : done ? (passed ? "Harbor verified this claim" : "Harbor found a problem with this claim") : "Harbor check"}
          </p>
        </div>
        {done && (
          <div className="flex gap-2">
            <Score label="Outcome" value={evaluation.outcome} />
            <Score label="Governance" value={evaluation.governance} />
          </div>
        )}
      </div>

      <p className="mt-2 text-xs text-muted-foreground">
        A one-task Harbor job, run on the same verifier as scenarios S01–S10. It only reads this claim, so it makes no AI calls.
        {evaluation?.expectation_source && (
          <>
            {" "}Expected result from: <span className="font-medium text-foreground">{evaluation.expectation_source}</span>.
          </>
        )}
      </p>

      {running && (
        <div className="mt-3 flex items-center gap-2 text-sm text-muted-foreground">
          <span className="h-2 w-2 animate-pulse rounded-full bg-chart-1" />
          Running the Harbor job (usually 15–30 s)…
        </div>
      )}

      {evaluation?.status === "error" && (
        <p className="mt-3 rounded-md bg-destructive/10 p-2 text-sm text-destructive">Harbor could not complete the check: {evaluation.error}</p>
      )}

      {done && evaluation.checks.length > 0 && (
        <div className="mt-3 grid gap-3 md:grid-cols-2">
          <CheckGroup title="Outcome: did the claim end correctly?" checks={evaluation.checks.filter((c) => c.group === "outcome")} />
          <CheckGroup title="Governance: does the audit trail prove it?" checks={evaluation.checks.filter((c) => c.group === "governance")} />
        </div>
      )}

      {done && (
        <p className="mt-3 font-mono text-[11px] text-muted-foreground">
          evals/harbor/claim_jobs/{evaluation.job}
          {evaluation.duration_s != null && ` · ${evaluation.duration_s.toFixed(1)} s`}
        </p>
      )}
    </section>
  );
}

function Score({ label, value }: { label: string; value: number | null }) {
  const ok = value === 1;
  return (
    <span className={`rounded-md px-2 py-1 text-xs font-semibold ${ok ? "bg-success/10 text-success" : "bg-destructive/10 text-destructive"}`}>
      {label} {ok ? "✓" : "✗"}
    </span>
  );
}

function CheckGroup({ title, checks }: { title: string; checks: ClaimEvaluationCheck[] }) {
  return (
    <div>
      <p className="mb-1.5 text-xs font-semibold text-card-foreground">{title}</p>
      <ul className="flex flex-col gap-1.5">
        {checks.map((c) => (
          <li key={c.id} className="flex gap-2 text-xs">
            <span className={`font-semibold ${c.passed ? "text-success" : "text-destructive"}`}>{c.passed ? "✓" : "✗"}</span>
            <span>
              <span className="text-card-foreground">{c.label}</span>
              <span className="block text-muted-foreground">{c.detail}</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
  );
}
