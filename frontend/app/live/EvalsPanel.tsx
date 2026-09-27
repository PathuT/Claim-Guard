"use client";

import useSWR from "swr";
import { type EvalTrial, getLatestEvals } from "@/lib/api";

/** Harbor evaluation scoreboard: the ten S01–S10 scenarios re-run as
 * automated tests against the real stack (no Docker — a custom local-host
 * Harbor environment), each scored on BOTH the business outcome and the
 * governance evidence in the audit trail. Reads the latest job written by
 * `npm run eval` (evals/harbor/jobs/). */
export function EvalsPanel() {
  const { data: job, error, isLoading, mutate } = useSWR("latest-evals", getLatestEvals, { refreshInterval: 10_000 });

  return (
    <section id="evals" className="scroll-mt-20 rounded-lg border border-border bg-card p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold text-card-foreground">Automated evaluation — Harbor</h2>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            Every scenario (happy path, room-rent cap, waiting period, duplicate bill, inflated amount, prompt
            injection, scope attack, expired-token replay, missing document, watchlisted hospital) is replayed through
            the real system by Harbor and scored twice: <span className="font-medium text-foreground">did the claim end correctly</span>, and{" "}
            <span className="font-medium text-foreground">does the audit trail prove the right rules fired</span>. No Docker — a
            custom Harbor environment runs each task on this machine.
          </p>
        </div>
        <button type="button" onClick={() => mutate()} className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground hover:text-foreground">
          Refresh
        </button>
      </div>

      {isLoading && <p className="mt-4 text-sm text-muted-foreground">Loading latest eval run…</p>}
      {error && <p className="mt-4 text-sm text-destructive">Could not load eval results — is AgentOS running?</p>}
      {!isLoading && !error && !job && (
        <p className="mt-4 rounded-md bg-secondary p-3 text-sm text-muted-foreground">
          No Harbor run yet. With the stack running, run <code className="font-mono">npm run eval</code> from the repo root.
        </p>
      )}

      {job && (
        <>
          <div className="mt-4 flex flex-wrap gap-3">
            <Stat label="Scenarios" value={String(job.n_trials)} />
            <Stat label="Outcome pass rate" value={pct(job.outcome_pass_rate)} good={job.outcome_pass_rate === 1} />
            <Stat label="Governance pass rate" value={pct(job.governance_pass_rate)} good={job.governance_pass_rate === 1} />
            <Stat label="Run" value={job.finished ? job.job.replace("__", " ") : "in progress…"} />
          </div>
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[40rem] text-left text-sm">
              <thead className="text-xs text-muted-foreground">
                <tr className="border-b border-border">
                  <th className="py-2 pr-3 font-medium">Scenario</th>
                  <th className="py-2 pr-3 font-medium">What it tests</th>
                  <th className="py-2 pr-3 font-medium">Outcome</th>
                  <th className="py-2 pr-3 font-medium">Governance</th>
                  <th className="py-2 font-medium">Time</th>
                </tr>
              </thead>
              <tbody>
                {job.trials.map((t) => (
                  <Row key={t.scenario} trial={t} />
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </section>
  );
}

function pct(v: number | null): string {
  return v == null ? "—" : `${Math.round(v * 100)}%`;
}

function Stat({ label, value, good }: { label: string; value: string; good?: boolean }) {
  return (
    <div className="rounded-md bg-secondary px-4 py-2">
      <p className="text-[11px] uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`text-lg font-semibold tabular-nums ${good ? "text-success" : "text-card-foreground"}`}>{value}</p>
    </div>
  );
}

function Score({ value }: { value: number | null }) {
  if (value == null) return <span className="text-muted-foreground">—</span>;
  return value === 1 ? <span className="font-semibold text-success">✓ pass</span> : <span className="font-semibold text-destructive">✗ fail</span>;
}

function Row({ trial }: { trial: EvalTrial }) {
  const problem = trial.error ?? (trial.failures.length ? trial.failures.join("; ") : null);
  return (
    <tr className="border-b border-border align-top last:border-b-0">
      <td className="py-2 pr-3 font-mono text-xs font-semibold">{trial.scenario}</td>
      <td className="py-2 pr-3 text-xs text-muted-foreground">
        {trial.description}
        {problem && <span className="mt-0.5 block text-destructive">{problem}</span>}
      </td>
      <td className="py-2 pr-3 text-xs">
        <Score value={trial.outcome} />
      </td>
      <td className="py-2 pr-3 text-xs">
        <Score value={trial.governance} />
      </td>
      <td className="py-2 text-xs tabular-nums text-muted-foreground">{trial.duration_s != null ? `${Math.round(trial.duration_s)} s` : "—"}</td>
    </tr>
  );
}
