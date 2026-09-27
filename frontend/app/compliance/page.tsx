"use client";

import { useState } from "react";
import useSWR from "swr";
import { ApiError, getAuditLog, getComplianceSummary } from "@/lib/api";
import { RULE_TEXT } from "@/lib/liveRun";

const VERDICT_STYLES: Record<string, string> = {
  allowed: "bg-success/10 text-success",
  blocked: "bg-destructive/10 text-destructive",
  shadow: "bg-muted text-muted-foreground",
  error: "bg-destructive/10 text-destructive",
  pending: "bg-warning/10 text-warning",
};

const VERDICT_FILTERS = [
  { value: undefined, label: "All" },
  { value: "blocked", label: "Denials only" },
  { value: "allowed", label: "Allowed only" },
] as const;

/** Compliance officer view (Divya): the governance evidence a regulator or
 * auditor would ask for — is the audit trail intact, what was refused and
 * why, who touched sensitive data — backed by the live AGT FlightRecorder. */
export default function CompliancePage() {
  const [verdict, setVerdict] = useState<string | undefined>(undefined);
  const { data: summary, error: summaryError } = useSWR("compliance-summary", getComplianceSummary, { refreshInterval: 15_000 });
  const { data, error, isLoading } = useSWR(["audit-log", verdict], () => getAuditLog({ policyVerdict: verdict, limit: 200 }));
  const entries = data?.entries ?? [];
  const loadError = error ? (error instanceof ApiError ? error.message : "Something went wrong.") : null;

  const allowed = summary?.stats.by_verdict.allowed ?? 0;
  const blocked = summary?.stats.by_verdict.blocked ?? 0;
  const denials = Object.entries(summary?.denied_by_rule ?? {}).sort((a, b) => b[1] - a[1]);
  const topAgents = summary?.stats.top_agents ?? [];
  const maxAgent = Math.max(1, ...topAgents.map((a) => a.count));

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Compliance — governance evidence</h1>
        <p className="mt-1 max-w-3xl text-sm text-muted-foreground">
          Every action any agent (or officer) attempted passes the AGT governance adapter, which records its verdict in an
          append-only, hash-chained audit log before anything executes. This page reads that log live.
        </p>
      </div>

      {summaryError && <p className="text-sm text-destructive">Could not load the compliance summary — is AgentOS running?</p>}

      {summary && (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Kpi label="Governed decisions" value={summary.stats.total_actions.toLocaleString("en-IN")} />
            <Kpi label="Allowed" value={allowed.toLocaleString("en-IN")} tone="success" />
            <Kpi label="Denied by policy" value={blocked.toLocaleString("en-IN")} tone={blocked ? "danger" : undefined} />
            <Kpi
              label="Audit hash chain"
              value={summary.integrity.valid ? "Intact ✓" : "Broken ✗"}
              tone={summary.integrity.valid ? "success" : "danger"}
              hint={summary.integrity.valid ? `${summary.integrity.total_entries} entries verified` : `first broken entry #${summary.integrity.first_tampered_id}`}
            />
          </div>

          <div className="grid gap-4 lg:grid-cols-3">
            <Panel title="Denials by rule" subtitle="Deterministic rules that refused an action — the attacks and mistakes that didn't happen.">
              {denials.length === 0 ? (
                <p className="text-sm text-muted-foreground">No denials yet.</p>
              ) : (
                <ul className="flex flex-col gap-2">
                  {denials.map(([rule, count]) => (
                    <li key={rule} className="flex items-start justify-between gap-3 text-sm">
                      <span>
                        <span className="font-mono font-semibold text-destructive">{rule}</span>
                        <span className="block text-xs text-muted-foreground">{RULE_TEXT[rule] ?? "policy rule"}</span>
                      </span>
                      <span className="rounded-full bg-destructive/10 px-2 py-0.5 text-xs font-semibold tabular-nums text-destructive">{count}</span>
                    </li>
                  ))}
                </ul>
              )}
            </Panel>

            <Panel title="Activity by agent" subtitle="Governed tool calls per agent identity.">
              <ul className="flex flex-col gap-2">
                {topAgents.map((a) => (
                  <li key={a.agent_id} className="text-sm">
                    <div className="flex justify-between">
                      <span className="font-mono text-card-foreground">{a.agent_id}</span>
                      <span className="tabular-nums text-muted-foreground">{a.count}</span>
                    </div>
                    <div className="mt-1 h-1.5 rounded-full bg-secondary">
                      <div className="h-1.5 rounded-full bg-chart-1" style={{ width: `${(a.count / maxAgent) * 100}%` }} />
                    </div>
                  </li>
                ))}
              </ul>
            </Panel>

            <Panel title="Sensitive-data access" subtitle="Who saw medical text, and every human override.">
              <p className="text-sm text-card-foreground">
                <span className="font-semibold">Medical text:</span> only the medical reviewer agent reads it, and only inside the claim
                workflow. Every other agent gets a coded finding (ICD-10 + flags). Any other agent that asks for medical records is
                refused (DATA-001, GOV-003).
              </p>
              <p className="mt-3 text-sm text-card-foreground">
                <span className="font-semibold">Officer break-glass:</span> {summary.break_glass_accesses.length} access
                {summary.break_glass_accesses.length === 1 ? "" : "es"}, each with a recorded reason.
              </p>
              {summary.break_glass_accesses.length > 0 && (
                <ul className="mt-2 flex flex-col gap-1 text-xs text-muted-foreground">
                  {summary.break_glass_accesses.slice(-5).map((b) => (
                    <li key={b.trace_id}>
                      <span className="font-mono">{new Date(b.timestamp).toLocaleString()}</span> · {b.officer_id ?? "officer"} — “{b.reason ?? "no reason recorded"}”
                    </li>
                  ))}
                </ul>
              )}
            </Panel>
          </div>
        </>
      )}

      <section className="flex flex-col gap-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-semibold text-card-foreground">Audit log</h2>
          <div className="flex gap-2">
            {VERDICT_FILTERS.map((f) => (
              <button
                key={f.label}
                onClick={() => setVerdict(f.value)}
                className={`rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                  verdict === f.value ? "bg-primary text-primary-foreground" : "bg-secondary text-muted-foreground hover:bg-muted"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
        </div>

        {isLoading && <p className="text-sm text-muted-foreground">Loading audit log…</p>}
        {loadError && <p className="text-sm text-destructive">{loadError}</p>}

        {!isLoading && !loadError && (
          <div className="overflow-x-auto rounded-lg border border-border bg-card">
            <table className="w-full text-left text-sm">
              <thead className="border-b border-border bg-secondary text-xs uppercase tracking-wide text-muted-foreground">
                <tr>
                  <th className="px-4 py-2">Timestamp</th>
                  <th className="px-4 py-2">Agent</th>
                  <th className="px-4 py-2">Tool</th>
                  <th className="px-4 py-2">Verdict</th>
                  <th className="px-4 py-2">Reason</th>
                </tr>
              </thead>
              <tbody>
                {entries.length === 0 && (
                  <tr>
                    <td colSpan={5} className="px-4 py-6 text-center text-muted-foreground">
                      No entries match this filter.
                    </td>
                  </tr>
                )}
                {entries.map((e) => (
                  <tr key={e.trace_id} className="border-b border-border last:border-0">
                    <td className="whitespace-nowrap px-4 py-2 font-mono text-xs tabular-nums text-muted-foreground">{new Date(e.timestamp).toLocaleString()}</td>
                    <td className="px-4 py-2 font-medium text-card-foreground">{e.agent_id}</td>
                    <td className="px-4 py-2 font-mono text-xs text-card-foreground">{e.tool_name}</td>
                    <td className="px-4 py-2">
                      <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${VERDICT_STYLES[e.policy_verdict] ?? "bg-muted text-muted-foreground"}`}>{e.policy_verdict}</span>
                    </td>
                    <td className="px-4 py-2 text-xs text-muted-foreground">{e.violation_reason ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}

function Kpi({ label, value, tone, hint }: { label: string; value: string; tone?: "success" | "danger"; hint?: string }) {
  const color = tone === "success" ? "text-success" : tone === "danger" ? "text-destructive" : "text-card-foreground";
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <p className="text-xs uppercase tracking-wide text-muted-foreground">{label}</p>
      <p className={`mt-1 text-2xl font-semibold tabular-nums ${color}`}>{value}</p>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}
    </div>
  );
}

function Panel({ title, subtitle, children }: { title: string; subtitle: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <p className="font-semibold text-card-foreground">{title}</p>
      <p className="mb-3 text-xs text-muted-foreground">{subtitle}</p>
      {children}
    </div>
  );
}
