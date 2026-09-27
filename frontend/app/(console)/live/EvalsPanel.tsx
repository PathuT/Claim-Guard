"use client";

import { useState } from "react";
import useSWR from "swr";
import { ApiError, type ClaimCheckSummary, type SuiteRow, getSuite, listClaimChecks, runSuite } from "@/lib/api";

/** Harbor, live. Two views of the same evaluator:
 * - the S01–S10 scenario suite: each scenario's latest result, run from
 *   this page (all, or one at a time) with progress as Harbor works;
 * - every Live Run claim: the per-claim check Harbor runs after each claim.
 * Both score the business outcome AND the governance evidence in the audit
 * trail, with a custom no-Docker Harbor environment on this machine. */
export function EvalsPanel() {
  const [tab, setTab] = useState<"suite" | "claims">("suite");
  return (
    <section id="evals" className="scroll-mt-20 rounded-xl border border-border bg-card shadow-sm p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="font-semibold text-card-foreground">Automated evaluation — Harbor</h2>
          <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
            Harbor replays claims through the real system and scores each one twice:{" "}
            <span className="font-medium text-foreground">did it end correctly</span>, and{" "}
            <span className="font-medium text-foreground">does the audit trail prove the right rules fired</span>. It runs on
            this machine through a custom environment, with no Docker.
          </p>
        </div>
        <div className="flex gap-1 rounded-md bg-secondary p-1">
          {(
            [
              ["suite", "Scenario suite S01–S10"],
              ["claims", "Every Live Run claim"],
            ] as const
          ).map(([id, label]) => (
            <button
              key={id}
              type="button"
              onClick={() => setTab(id)}
              className={`rounded px-3 py-1.5 text-xs font-medium transition-colors ${tab === id ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
            >
              {label}
            </button>
          ))}
        </div>
      </div>
      {tab === "suite" ? <SuiteView /> : <ClaimChecksView />}
    </section>
  );
}

function SuiteView() {
  const { data: suite, error, isLoading, mutate } = useSWR("harbor-suite", getSuite, {
    refreshInterval: (latest) => (latest?.run && !latest.run.finished ? 3000 : 15_000),
  });
  const [confirming, setConfirming] = useState<string[] | null>(null);
  const [startError, setStartError] = useState<string | null>(null);

  const running = suite?.run != null && !suite.run.finished;
  const progress = running && suite?.run ? suite.rows.filter((r) => suite.run!.scenarios.includes(r.scenario) && r.state === "done" && r.ran_at && Date.parse(r.ran_at) >= suite.run!.started_at * 1000).length : 0;
  const current = suite?.rows.find((r) => r.state === "running");

  async function start(scenarios: string[]) {
    setConfirming(null);
    setStartError(null);
    try {
      await runSuite(scenarios);
      await mutate();
    } catch (err) {
      setStartError(
        err instanceof ApiError && err.status === 404 && !err.reasonCode
          ? "AgentOS is running an older build. Restart `npm run dev` to enable running Harbor from here."
          : err instanceof ApiError
            ? err.message
            : "Could not start Harbor.",
      );
    }
  }

  if (isLoading) return <p className="mt-4 text-sm text-muted-foreground">Loading Harbor results…</p>;
  if (error || !suite)
    return (
      <p className="mt-4 text-sm text-destructive">
        {error instanceof ApiError && error.status === 404 ? "AgentOS is running an older build — restart `npm run dev`." : "Could not load Harbor results — is AgentOS running?"}
      </p>
    );

  const needsAi = (ids: string[]) => suite.rows.filter((r) => ids.includes(r.scenario) && r.uses_ai).length;
  // Expected time per AI scenario, from the durations of the last real runs.
  const aiDurations = suite.rows.filter((r) => r.uses_ai && r.duration_s != null).map((r) => r.duration_s as number);
  const avgAi = aiDurations.length ? Math.round(aiDurations.reduce((x, y) => x + y, 0) / aiDurations.length) : null;

  return (
    <>
      <div className="mt-4 flex flex-wrap items-stretch gap-3">
        <Stat label="Scored" value={`${suite.scored}/${suite.rows.length}`} />
        <Stat label="Outcome pass rate" value={pct(suite.outcome_pass_rate)} good={suite.outcome_pass_rate === 1} />
        <Stat label="Governance pass rate" value={pct(suite.governance_pass_rate)} good={suite.governance_pass_rate === 1} />
        <Stat label="Last result" value={suite.last_run_at ? when(suite.last_run_at) : "never"} />
        <div className="ml-auto flex items-center gap-2">
          <button
            type="button"
            disabled={running}
            onClick={() => setConfirming(suite.rows.map((r) => r.scenario))}
            className="rounded-md bg-primary px-3 py-2 text-xs font-semibold text-primary-foreground transition-opacity disabled:opacity-40"
          >
            Run all {suite.rows.length} scenarios
          </button>
        </div>
      </div>

      {confirming && (
        <div className="mt-3 flex flex-wrap items-center justify-between gap-3 rounded-md border border-warning/50 bg-warning/10 p-3 text-sm">
          <span className="text-card-foreground">
            Run <span className="font-mono font-semibold">{confirming.length === suite.rows.length ? "S01–S10" : confirming.join(", ")}</span> through Harbor?{" "}
            {needsAi(confirming) > 0 ? (
              <>
                {needsAi(confirming)} scenario(s) replay a claim through the live AI agents ({avgAi ? `about ${avgAi} s each, from the last runs` : "about a minute each"}, uses the Groq quota), so
                don&apos;t start a Live Run claim until it finishes.
              </>
            ) : (
              <>This is a governance attack probe: no AI calls.</>
            )}
          </span>
          <span className="flex gap-2">
            <button type="button" onClick={() => start(confirming.length === suite.rows.length ? [] : confirming)} className="rounded-md bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground">
              Start
            </button>
            <button type="button" onClick={() => setConfirming(null)} className="rounded-md border border-border px-3 py-1.5 text-xs font-medium text-muted-foreground">
              Cancel
            </button>
          </span>
        </div>
      )}
      {startError && <p className="mt-3 rounded-md bg-destructive/10 p-2 text-sm text-destructive">{startError}</p>}

      {running && suite.run && (
        <div className="mt-3 rounded-md border border-chart-1/40 bg-chart-1/5 p-3">
          <div className="flex items-center justify-between text-xs">
            <span className="flex items-center gap-2 font-medium text-chart-1">
              <span className="h-2 w-2 animate-pulse rounded-full bg-chart-1" />
              Harbor is running {current ? <span className="font-mono">{current.scenario}</span> : "…"}
            </span>
            <span className="tabular-nums text-muted-foreground">
              {progress} / {suite.run.scenarios.length} done
            </span>
          </div>
          <div className="mt-2 h-1.5 overflow-hidden rounded-full bg-secondary">
            <div className="h-full rounded-full bg-chart-1 transition-all" style={{ width: `${(progress / suite.run.scenarios.length) * 100}%` }} />
          </div>
        </div>
      )}

      <div className="mt-4 overflow-x-auto">
        <table className="w-full min-w-[52rem] text-left text-sm">
          <thead className="text-xs text-muted-foreground">
            <tr className="border-b border-border">
              <th className="py-2 pr-3 font-medium">Scenario</th>
              <th className="py-2 pr-3 font-medium">What it tests · what Harbor verifies</th>
              <th className="py-2 pr-3 font-medium">Outcome</th>
              <th className="py-2 pr-3 font-medium">Governance</th>
              <th className="py-2 pr-3 font-medium">Time</th>
              <th className="py-2 pr-3 font-medium">Ran</th>
              <th className="py-2 font-medium" />
            </tr>
          </thead>
          <tbody>
            {suite.rows.map((row) => (
              <SuiteRowView key={row.scenario} row={row} disabled={running} onRun={() => setConfirming([row.scenario])} />
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}

function SuiteRowView({ row, disabled, onRun }: { row: SuiteRow; disabled: boolean; onRun: () => void }) {
  const problem = row.error ?? (row.failures.length ? row.failures.join("; ") : null);
  const live = row.state === "running" || row.state === "queued";
  return (
    <tr className={`border-b border-border align-top last:border-b-0 ${row.state === "running" ? "bg-chart-1/5" : ""}`}>
      <td className="py-2 pr-3">
        <span className="font-mono text-xs font-semibold">{row.scenario}</span>
        <span className={`mt-1 block w-fit rounded px-1.5 py-0.5 text-[10px] ${row.uses_ai ? "bg-chart-1/10 text-chart-1" : "bg-secondary text-muted-foreground"}`}>
          {row.uses_ai ? "AI agents" : "no AI"}
        </span>
      </td>
      <td className="py-2 pr-3 text-xs">
        <span className="text-card-foreground">{row.description}</span>
        <span className="mt-1 flex flex-wrap gap-1">
          {row.verifies.map((v) => (
            <span key={v} className="rounded border border-border px-1.5 py-0.5 text-[10px] text-muted-foreground">
              {v}
            </span>
          ))}
        </span>
        {problem && !live && <span className="mt-1 block text-destructive">{problem}</span>}
      </td>
      <td className="py-2 pr-3 text-xs">{live ? <Pending state={row.state} /> : <Score value={row.outcome} />}</td>
      <td className="py-2 pr-3 text-xs">{live ? <Pending state={row.state} /> : <Score value={row.governance} />}</td>
      <td className="py-2 pr-3 text-xs tabular-nums text-muted-foreground">{row.duration_s != null && !live ? `${Math.round(row.duration_s)} s` : "—"}</td>
      <td className="py-2 pr-3 text-xs text-muted-foreground">{row.ran_at && !live ? when(row.ran_at) : "—"}</td>
      <td className="py-2 text-right">
        <button type="button" disabled={disabled} onClick={onRun} className="rounded border border-border px-2 py-1 text-[11px] font-medium text-muted-foreground hover:text-foreground disabled:opacity-40">
          Run
        </button>
      </td>
    </tr>
  );
}

function ClaimChecksView() {
  const { data, error, isLoading } = useSWR("harbor-claim-checks", listClaimChecks, { refreshInterval: 10_000 });
  if (isLoading) return <p className="mt-4 text-sm text-muted-foreground">Loading claim checks…</p>;
  if (error)
    return (
      <p className="mt-4 text-sm text-destructive">
        {error instanceof ApiError && error.status === 404 ? "AgentOS is running an older build — restart `npm run dev`." : "Could not load claim checks — is AgentOS running?"}
      </p>
    );
  if (!data || data.length === 0)
    return (
      <p className="mt-4 rounded-md bg-secondary p-3 text-sm text-muted-foreground">
        No claim checked yet. Run a claim above: when it finishes, Harbor checks it automatically and it appears here.
      </p>
    );
  const passed = data.filter((c) => c.outcome === 1 && c.governance === 1).length;
  return (
    <>
      <div className="mt-4 flex flex-wrap gap-3">
        <Stat label="Claims checked" value={String(data.length)} />
        <Stat label="Passed both" value={`${passed}/${data.length}`} good={passed === data.length} />
      </div>
      <ul className="mt-4 flex flex-col gap-2">
        {data.map((check) => (
          <ClaimCheckRow key={check.job} check={check} />
        ))}
      </ul>
    </>
  );
}

function ClaimCheckRow({ check }: { check: ClaimCheckSummary }) {
  const failed = check.checks.filter((c) => !c.passed);
  return (
    <li className="rounded-md border border-border">
      <details>
        <summary className="flex cursor-pointer flex-wrap items-center gap-x-4 gap-y-1 px-3 py-2 text-sm">
          <span className="font-mono text-xs font-semibold">{check.claim_id}</span>
          <span className="text-xs text-muted-foreground">{check.ran_at ? when(check.ran_at) : ""}</span>
          <span className="text-xs text-muted-foreground">{check.expectation_source}</span>
          <span className="ml-auto flex gap-3 text-xs">
            <span>
              Outcome <Score value={check.outcome} />
            </span>
            <span>
              Governance <Score value={check.governance} />
            </span>
            <span className="text-muted-foreground">{failed.length ? `${failed.length} failed` : `${check.checks.length} checks`}</span>
          </span>
        </summary>
        <ul className="grid gap-1.5 border-t border-border px-3 py-2 md:grid-cols-2">
          {check.error && <li className="text-xs text-destructive">{check.error}</li>}
          {check.checks.map((c) => (
            <li key={c.id} className="flex gap-2 text-xs">
              <span className={`font-semibold ${c.passed ? "text-success" : "text-destructive"}`}>{c.passed ? "✓" : "✗"}</span>
              <span>
                <span className="text-card-foreground">{c.label}</span>
                <span className="text-muted-foreground"> — {c.detail}</span>
              </span>
            </li>
          ))}
        </ul>
      </details>
    </li>
  );
}

function when(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  const sameDay = date.toDateString() === new Date().toDateString();
  const time = date.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" });
  return sameDay ? `today ${time}` : `${date.toLocaleDateString("en-IN", { day: "numeric", month: "short" })} ${time}`;
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

function Pending({ state }: { state: string }) {
  return state === "running" ? (
    <span className="flex items-center gap-1 font-medium text-chart-1">
      <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-chart-1" /> running
    </span>
  ) : (
    <span className="text-muted-foreground">queued</span>
  );
}

function Score({ value }: { value: number | null }) {
  if (value == null) return <span className="text-muted-foreground">—</span>;
  return value === 1 ? <span className="font-semibold text-success">✓ pass</span> : <span className="font-semibold text-destructive">✗ fail</span>;
}
