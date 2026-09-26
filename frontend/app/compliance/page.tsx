"use client";

import { useState } from "react";
import useSWR from "swr";
import { ApiError, getAuditLog } from "@/lib/api";

const VERDICT_STYLES: Record<string, string> = {
  allowed: "bg-emerald-100 text-emerald-700",
  blocked: "bg-red-100 text-red-700",
  shadow: "bg-slate-100 text-slate-700",
  error: "bg-red-100 text-red-700",
  pending: "bg-amber-100 text-amber-800",
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
        <p className="mt-1 max-w-2xl text-sm text-slate-600">
          Every tool call any agent attempted, and the governance layer&apos;s verdict on it — allowed or blocked,
          by rule_id. This is the system-wide log; see a specific claim&apos;s own submission response for its
          per-claim audit trail.
        </p>
        <p className="mt-2 max-w-2xl rounded-md bg-amber-50 p-3 text-xs text-amber-800">
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
              verdict === f.value ? "bg-slate-900 text-white" : "bg-slate-100 text-slate-700 hover:bg-slate-200"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {loading && <p className="text-sm text-slate-500">Loading audit log…</p>}
      {loadError && <p className="text-sm text-red-600">{loadError}</p>}

      {!loading && !loadError && (
        <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
          <table className="w-full text-left text-sm">
            <thead className="border-b border-slate-200 bg-slate-50 text-xs uppercase tracking-wide text-slate-500">
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
                  <td colSpan={5} className="px-4 py-6 text-center text-slate-400">
                    No entries match this filter.
                  </td>
                </tr>
              )}
              {entries.map((e) => (
                <tr key={e.trace_id} className="border-b border-slate-100 last:border-0">
                  <td className="px-4 py-2 whitespace-nowrap text-xs text-slate-500">
                    {new Date(e.timestamp).toLocaleString()}
                  </td>
                  <td className="px-4 py-2 font-medium">{e.agent_id}</td>
                  <td className="px-4 py-2 font-mono text-xs">{e.tool_name}</td>
                  <td className="px-4 py-2">
                    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${VERDICT_STYLES[e.policy_verdict] ?? "bg-slate-100 text-slate-700"}`}>
                      {e.policy_verdict}
                    </span>
                  </td>
                  <td className="px-4 py-2 text-xs text-slate-600">{e.violation_reason ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
