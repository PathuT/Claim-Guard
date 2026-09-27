"use client";

import { useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";
import { PageHeader } from "@/app/_components/PageHeader";
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
  fraud: ["search_claims_pseudonymised", "read_hospital"],
  payout: ["execute_payout"],
};

export default function PipelinePage() {
  return (
    <Suspense fallback={null}>
      <Pipeline />
    </Suspense>
  );
}

function Pipeline() {
  // ?claim=<id> (e.g. from the dashboard's latest claims) opens that claim.
  const initial = useSearchParams().get("claim");
  const [claimId, setClaimId] = useState(initial ?? "");
  const [activeClaimId, setActiveClaimId] = useState<string | null>(initial);

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
      <PageHeader
        eyebrow="Agno Workflow · claim-assessment"
        title="Agent pipeline"
        description="Every claim runs through one Agno Workflow: four Agno agents (intake, medical reviewer, coverage, fraud) plus the settlement engine, tiering and payout, with a Condition deciding auto-pay (T2) or a human officer (T3). Each step passes forward a typed result, never raw medical text. Load a claim to see each step's stored output and which steps made governed calls."
      />

      <form onSubmit={handleLoad} className="flex gap-2">
        <input
          value={claimId}
          onChange={(e) => setClaimId(e.target.value)}
          placeholder="e.g. CLM-2026-018836"
          className="h-10 max-w-sm flex-1 rounded-lg border border-border bg-card px-3 text-sm shadow-sm outline-none focus:border-chart-1 focus:ring-4 focus:ring-chart-1/15"
        />
        <button type="submit" className="h-10 rounded-lg bg-primary px-4 text-sm font-semibold text-primary-foreground shadow-sm hover:opacity-90">
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
            className="rounded-full border border-border bg-card px-3 py-1 text-xs font-medium text-muted-foreground hover:border-primary/40"
          >
            {s.id}
          </button>
        ))}
      </div>

      {statusLoading && <p className="text-sm text-muted-foreground">Loading…</p>}
      {statusError && <p className="text-sm text-destructive">{statusError instanceof ApiError ? statusError.message : "Something went wrong."}</p>}

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
      <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground" title="This agent's work is a structured in-process output, not a gateway-audited tool call — see the page's own explanation.">
        no audit entry (in-process)
      </span>
    );
  }
  const matches = entries.filter((e) => e.agent_id === agentId && tools.includes(e.tool_name));
  if (matches.length === 0) {
    return <span className="rounded-full bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground">not yet in audit log</span>;
  }
  return (
    <span className="rounded-full bg-success/10 px-2 py-0.5 text-[10px] font-medium text-success">
      {matches.length} audited call{matches.length > 1 ? "s" : ""} · {matches[0].policy_verdict}
    </span>
  );
}

function StepCard({ title, agentId, auditEntries, children }: { title: string; agentId: string; auditEntries: AuditEntry[]; children: React.ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-card shadow-sm p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-semibold text-card-foreground">{title}</h3>
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
      <div className="rounded-lg border border-warning/40 bg-warning/10 p-4 text-sm text-warning">
        Status: <strong>{status.status}</strong>. No assessment recorded — either the claim hasn&apos;t been
        submitted yet, or it stopped before any agent ran (e.g. a missing required document routes straight to{" "}
        <code>needs_resubmission</code>).
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      <StepCard title="1 · Intake agent (Agno)" agentId="intake" auditEntries={auditEntries}>
        {a.intake_summary ? (
          <div className="text-sm text-card-foreground">
            <p className="tabular-nums">Bill total: {formatInr(a.intake_summary.bill_total)} · Stay: {a.intake_summary.length_of_stay_hours}h</p>
            <ul className="mt-1 text-xs text-muted-foreground">
              {a.intake_summary.line_items.map((li, i) => (
                <li key={i} className="tabular-nums">{li.label}: {formatInr(li.amount)}</li>
              ))}
            </ul>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">No intake summary recorded for this claim yet.</p>
        )}
      </StepCard>

      <StepCard title="2 · Medical reviewer agent (Agno)" agentId="medical_reviewer" auditEntries={auditEntries}>
        {a.medical_finding ? (
          <div className="text-sm text-card-foreground">
            <p>ICD-10 {a.medical_finding.icd10} · {a.medical_finding.diagnosis_category} · confidence {(a.medical_finding.confidence * 100).toFixed(0)}%</p>
            <p className="mt-1 text-xs text-muted-foreground">{a.medical_finding.notes_for_officer}</p>
          </div>
        ) : (
          <p className="text-xs text-muted-foreground">No medical finding recorded for this claim yet.</p>
        )}
      </StepCard>

      <StepCard title="3 · Settlement (code) + coverage agent (Agno)" agentId="coverage" auditEntries={auditEntries}>
        <p className="text-sm tabular-nums text-card-foreground">Payable: {formatInr(a.payable_amount)} of {formatInr(a.claimed_amount)} claimed</p>
        {a.deductions.length > 0 && (
          <ul className="mt-1 text-xs text-muted-foreground">
            {a.deductions.map((d, i) => (
              <li key={i} className="tabular-nums">−{formatInr(d.amount)} ({d.clause_id}): {d.reason}</li>
            ))}
          </ul>
        )}
        {a.flags.length > 0 && <p className="mt-1 text-xs text-warning">Flags: {a.flags.join(", ")}</p>}
      </StepCard>

      <StepCard title="4 · Fraud agent (Agno) — governed data access" agentId="fraud" auditEntries={auditEntries}>
        {a.fraud_flags.length === 0 ? (
          <p className="text-xs text-muted-foreground">No fraud signals detected.</p>
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

      <StepCard title="5 · Tier → governed payout or officer (Condition)" agentId="payout" auditEntries={auditEntries}>
        <p className="text-sm text-card-foreground">
          Final state: <strong>{status.status.replace(/_/g, " ")}</strong>
        </p>
        {status.status === "paid" ? (
          <p className="mt-1 text-xs text-success">Payout executed — every PAY-* rule (amount matches assessment, account matches registered, within remaining sum insured, no duplicate) passed.</p>
        ) : status.status === "pending_human" ? (
          <p className="mt-1 text-xs text-warning">Payout withheld — a human officer must decide (see the Officer view).</p>
        ) : null}
      </StepCard>

      <div className="rounded-md bg-secondary p-3 text-xs text-muted-foreground">
        &ldquo;no audit entry (in-process)&rdquo; means that step receives its inputs from the workflow (documents, or
        the previous step&apos;s typed result) and makes no data-access call of its own, so there is nothing for the
        governance layer to record. Every step that touches data or state does make governed calls, each checked by the
        AGT adapter and recorded in the audit log: <code>fraud</code> (pseudonymised claims + hospital watchlist, via a
        scoped token and the data gateway), <code>payout</code> (the money movement) and <code>supervisor</code> (every
        claim state transition). See the Compliance page for the audit log and Phoenix (localhost:6006) for the full
        trace.
      </div>
    </div>
  );
}
