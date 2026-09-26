"use client";

import { useState } from "react";
import useSWR from "swr";
import { ApiError, type AuditEntry, type ClaimStatus, getClaimAudit, getClaimStatus } from "@/lib/api";
import { formatInr, severityStyle } from "@/lib/format";
import { DEMO_SCENARIOS } from "@/lib/demoScenarios";

/** Which real audit-log tool_name(s) count as evidence a given agent ran a
 * governed action — not every agent makes one (see the honesty note
 * below). Kept as data so a reader can check this against
 * governance/tool_allowlist.py themselves. */
const AGENT_AUDITED_TOOLS: Record<string, string[]> = {
  supervisor: ["set_claim_state"],
  payout: ["execute_payout"],
};

export default function PipelinePage() {
  const [claimId, setClaimId] = useState("");
  const [activeClaimId, setActiveClaimId] = useState<string | null>(null);

  const { data: status, error: statusError, isLoading: statusLoading } = useSWR(
    activeClaimId ? ["pipeline-status", activeClaimId] : null,
    () => getClaimStatus(activeClaimId!),
  );
  const { data: audit } = useSWR(
    activeClaimId ? ["pipeline-audit", activeClaimId] : null,
    () => getClaimAudit(activeClaimId!),
  );

  function handleLoad(e: React.FormEvent) {
    e.preventDefault();
    if (claimId.trim()) setActiveClaimId(claimId.trim());
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Agent pipeline</h1>
        <p className="mt-1 max-w-2xl text-sm text-slate-600">
          Every claim runs through 5 real agents, each seeing only what it needs and passing forward a structured
          result — never raw text — before a governed payout or human handoff. This view shows each agent&apos;s
          actual stored output for one claim, plus which steps are independently confirmed in the governance audit
          log.
        </p>
      </div>

      <form onSubmit={handleLoad} className="flex gap-2">
        <input
          value={claimId}
          onChange={(e) => setClaimId(e.target.value)}
          placeholder="e.g. CLM-2026-018836"
          className="flex-1 max-w-sm rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500"
        />
        <button type="submit" className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700">
          Load
        </button>
      </form>

      <div className="flex flex-wrap gap-2">
        {DEMO_SCENARIOS.map((s) => (
          <button
            key={s.id}
            onClick={() => {
              setClaimId(s.claimId);
              setActiveClaimId(s.claimId);
            }}
            className="rounded-full border border-slate-200 bg-white px-3 py-1 text-xs font-medium text-slate-600 hover:border-slate-400"
          >
            {s.id}
          </button>
        ))}
      </div>

      {statusLoading && <p className="text-sm text-slate-500">Loading…</p>}
      {statusError && <p className="text-sm text-red-600">{statusError instanceof ApiError ? statusError.message : "Something went wrong."}</p>}

      {status && (
        <PipelineView status={status} auditEntries={audit?.entries ?? []} />
      )}
    </div>
  );
}

function AuditBadge({ agentId, entries }: { agentId: string; entries: AuditEntry[] }) {
  const tools = AGENT_AUDITED_TOOLS[agentId];
  if (!tools) {
    return (
      <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500" title="This agent's work is a structured in-process output, not a gateway-audited tool call — see the page's own explanation.">
        no audit entry (in-process)
      </span>
    );
  }
  const matches = entries.filter((e) => e.agent_id === agentId && tools.includes(e.tool_name));
  if (matches.length === 0) {
    return <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-medium text-slate-500">not yet in audit log</span>;
  }
  return (
    <span className="rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
      {matches.length} audited call{matches.length > 1 ? "s" : ""} · {matches[0].policy_verdict}
    </span>
  );
}

function StepCard({ title, agentId, auditEntries, children }: { title: string; agentId: string; auditEntries: AuditEntry[]; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-slate-900">{title}</h3>
        <AuditBadge agentId={agentId} entries={auditEntries} />
      </div>
      <div className="mt-2">{children}</div>
    </div>
  );
}

function PipelineView({ status, auditEntries }: { status: ClaimStatus; auditEntries: AuditEntry[] }) {
  const a = status.assessment;

  if (!a) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-4 text-sm text-amber-800">
        Status: <strong>{status.status}</strong>. No assessment recorded — either the claim hasn&apos;t been
        submitted yet, or it stopped before any agent ran (e.g. a missing required document routes straight to{" "}
        <code>needs_resubmission</code>).
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <StepCard title="1 · Intake" agentId="intake" auditEntries={auditEntries}>
        {a.intake_summary ? (
          <div className="text-sm text-slate-700">
            <p>Bill total: {formatInr(a.intake_summary.bill_total)} · Stay: {a.intake_summary.length_of_stay_hours}h</p>
            <ul className="mt-1 text-xs text-slate-500">
              {a.intake_summary.line_items.map((li, i) => (
                <li key={i}>{li.label}: {formatInr(li.amount)}</li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-xs text-slate-400">No intake summary recorded for this claim yet.</p>
        )}
      </StepCard>

      <StepCard title="2 · Medical reviewer" agentId="medical_reviewer" auditEntries={auditEntries}>
        {a.medical_finding ? (
          <div className="text-sm text-slate-700">
            <p>ICD-10 {a.medical_finding.icd10} · {a.medical_finding.diagnosis_category} · confidence {(a.medical_finding.confidence * 100).toFixed(0)}%</p>
            <p className="mt-1 text-xs text-slate-500">{a.medical_finding.notes_for_officer}</p>
          </div>
        ) : (
          <p className="text-xs text-slate-400">No medical finding recorded for this claim yet.</p>
        )}
      </StepCard>

      <StepCard title="3 · Coverage" agentId="coverage" auditEntries={auditEntries}>
        <p className="text-sm text-slate-700">Payable: {formatInr(a.payable_amount)} of {formatInr(a.claimed_amount)} claimed</p>
        {a.deductions.length > 0 && (
          <ul className="mt-1 text-xs text-slate-500">
            {a.deductions.map((d, i) => (
              <li key={i}>−{formatInr(d.amount)} ({d.clause_id}): {d.reason}</li>
            ))}
          </ul>
        )}
        {a.flags.length > 0 && <p className="mt-1 text-xs text-amber-700">Flags: {a.flags.join(", ")}</p>}
      </StepCard>

      <StepCard title="4 · Fraud" agentId="fraud" auditEntries={auditEntries}>
        {a.fraud_flags.length === 0 ? (
          <p className="text-xs text-slate-400">No fraud signals detected.</p>
        ) : (
          <ul className="flex flex-col gap-1">
            {a.fraud_flags.map((f, i) => (
              <li key={i} className="flex items-center gap-2 text-sm">
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${severityStyle(f.severity)}`}>{f.severity}</span>
                {f.type}
              </li>
            ))}
          </ul>
        )}
      </StepCard>

      <StepCard title="5 · Payout" agentId="payout" auditEntries={auditEntries}>
        <p className="text-sm text-slate-700">
          Final state: <strong>{status.status.replace(/_/g, " ")}</strong>
        </p>
        {status.status === "paid" ? (
          <p className="mt-1 text-xs text-emerald-700">Payout executed — every PAY-* rule (amount matches assessment, account matches registered, within remaining sum insured, no duplicate) passed.</p>
        ) : status.status === "pending_human" ? (
          <p className="mt-1 text-xs text-amber-700">Payout withheld — a human officer must decide (see the Officer view).</p>
        ) : null}
      </StepCard>

      <div className="rounded-md bg-slate-50 p-3 text-xs text-slate-500">
        &ldquo;no audit entry (in-process)&rdquo; means that agent&apos;s work is a real, structured output (visible
        above) rather than a gateway-mediated tool call — it never queried the data gateway/token service directly,
        so nothing about it appears in the governance audit log. Only <code>supervisor</code> (state transitions)
        and <code>payout</code> (the actual money movement) make governed tool calls today. See the Compliance page
        for those real audit entries, and Phoenix (localhost:6006) for the full trace.
      </div>
    </div>
  );
}
