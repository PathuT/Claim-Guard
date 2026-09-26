"use client";

import { useState } from "react";
import useSWR from "swr";
import { ApiError, getAuditLog } from "@/lib/api";

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

export default function CompliancePage() {
  const [verdict, setVerdict] = useState<string | undefined>(undefined);
  // SWR key includes `verdict` so switching filters is a distinct cache
  // entry/request, not a manual "set loading, refetch, clear loading"
  // effect — isLoading/error are computed from the request's own state,
  // never set imperatively (Next.js 16's own client-fetching guide now
  // recommends SWR/TanStack Query over a hand-rolled useEffect for exactly
  // this: repeated fetches with loading/error UI — see node_modules/next/
  // dist/docs/01-app/02-guides/client-side-data-fetching).
  const { data, error, isLoading } = useSWR(["audit-log", verdict], () => getAuditLog({ policyVerdict: verdict, limit: 200 }));
  const entries = data?.entries ?? [];
  const loading = isLoading;
  const loadError = error ? (error instanceof ApiError ? error.message : "Something went wrong.") : null;

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Compliance — governance audit log</h1>
        <p className="mt-1 max-w-2xl text-sm text-muted-foreground">
          Every tool call any agent attempted, and the governance layer&apos;s verdict on it — allowed or blocked,
          by rule_id. This is the system-wide log; see a specific claim&apos;s own submission response for its
          per-claim audit trail.
        </p>
        <p className="mt-2 max-w-2xl rounded-md bg-warning/10 p-3 text-xs text-warning">
          Note: there is currently no medical-data-specific access filter here. The medical reviewer agent
          receives already-extracted diagnosis text as a plain argument from intake, in-process — not via a
          gateway-mediated tool call this log would capture — so a &ldquo;medical data access report&rdquo; filter
          would always show zero results today rather than reflecting a real gap in oversight.
        </p>
      </div>

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

      {loading && <p className="text-sm text-muted-foreground">Loading audit log…</p>}
      {loadError && <p className="text-sm text-destructive">{loadError}</p>}

      {!loading && !loadError && (
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
                  <td className="px-4 py-2 whitespace-nowrap text-xs font-mono tabular-nums text-muted-foreground">
                    {new Date(e.timestamp).toLocaleString()}
                  </td>
                  <td className="px-4 py-2 font-medium text-card-foreground">{e.agent_id}</td>
                  <td className="px-4 py-2 font-mono text-xs text-card-foreground">{e.tool_name}</td>
                  <td className="px-4 py-2">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${VERDICT_STYLES[e.policy_verdict] ?? "bg-muted text-muted-foreground"}`}>
                      {e.policy_verdict}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-xs text-muted-foreground">{e.violation_reason ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
