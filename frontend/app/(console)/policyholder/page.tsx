"use client";

import Link from "next/link";
import { useState } from "react";
import {
  ApiError,
  type ClaimSummary,
  type NewClaimFields,
  type NewClaimResult,
  type SubmitClaimResult,
  listClaims,
  submitClaim,
  submitNewClaim,
} from "@/lib/api";
import { PageHeader } from "@/app/_components/PageHeader";
import { useSessionUser } from "@/app/_components/SessionContext";
import { formatInr, humanizeStatus, statusStyle } from "@/lib/format";
import { UploadForm } from "../live/StartPanel";

type Phase = "idle" | "uploading" | "assessing" | "done";

/** Policyholder view (Priya): submit a reimbursement claim with the real
 * hospital PDFs, then see the decision and a settlement breakdown in which
 * every deduction cites the policy clause it comes from. The same claim can
 * be watched step by step, with every backend operation, on Live Run. */
export default function PolicyholderPage() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [created, setCreated] = useState<NewClaimResult | null>(null);
  const [result, setResult] = useState<SubmitClaimResult | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);

  const user = useSessionUser();
  // A signed-in policyholder's policy comes from the session, not a text box.
  const [policyNumber, setPolicyNumber] = useState(user?.role === "policyholder" ? user.actorId : "");
  const [claims, setClaims] = useState<ClaimSummary[] | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);

  async function handleUpload(fields: NewClaimFields) {
    setPhase("uploading");
    setSubmitError(null);
    setCreated(null);
    setResult(null);
    try {
      const newClaim = await submitNewClaim(fields);
      setCreated(newClaim);
      setPhase("assessing");
      setResult(await submitClaim(newClaim.claim_id));
    } catch (err) {
      setSubmitError(err instanceof ApiError ? `${err.message}${err.reasonCode ? ` (${err.reasonCode})` : ""}` : "Something went wrong.");
    } finally {
      setPhase("done");
    }
  }

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!policyNumber.trim()) return;
    setSearching(true);
    setSearchError(null);
    try {
      setClaims((await listClaims({ policyNumber: policyNumber.trim() })).claims);
    } catch (err) {
      setSearchError(err instanceof ApiError ? err.message : "Something went wrong.");
      setClaims(null);
    } finally {
      setSearching(false);
    }
  }

  const busy = phase === "uploading" || phase === "assessing";

  return (
    <div className="flex flex-col gap-8">
      <PageHeader
        eyebrow="Policyholder"
        title="Submit and track a claim"
        description={
          <>
            Paid the hospital yourself? Upload the final bill and discharge summary. The documents are read for real (PDF text
            extraction), assessed by the claim workflow, and you get a decision with every deduction explained against your policy.
            {user?.role !== "policyholder" && (
              <>
                {" "}To watch every backend step as it happens, use{" "}
                <Link href="/live" className="font-medium text-chart-1 underline">
                  Live Run
                </Link>
                .
              </>
            )}
          </>
        }
      />

      <section className="rounded-xl border border-border bg-card shadow-sm p-5">
        <h2 className="font-medium text-card-foreground">Submit a new claim</h2>
        <p className="mb-4 mt-1 text-xs text-muted-foreground">
          The documents and the stated illness are treated as untrusted input: they are read, never obeyed.
        </p>
        <UploadForm disabled={busy} onSubmit={handleUpload} />

        {phase !== "idle" && (
          <ol className="mt-5 flex flex-wrap items-center gap-2 text-xs">
            <Progress label="Documents uploaded & read" state={created ? "done" : phase === "uploading" ? "active" : "pending"} />
            <span className="text-muted-foreground">→</span>
            <Progress label="Agents assessing (≈ 1 min)" state={result ? "done" : phase === "assessing" ? "active" : "pending"} />
            <span className="text-muted-foreground">→</span>
            <Progress label="Decision" state={result ? "done" : "pending"} />
          </ol>
        )}
        {created && (
          <ul className="mt-3 flex flex-col gap-1 text-xs text-muted-foreground">
            {created.documents.map((d) => (
              <li key={d.doc_type}>
                <span className="font-medium text-foreground">{d.doc_type.replace("_", " ")}</span>: {d.pages} page(s),{" "}
                {d.extracted_chars.toLocaleString("en-IN")} characters extracted, fingerprint {d.sha256.slice(0, 12)}…
              </li>
            ))}
          </ul>
        )}
        {submitError && <p className="mt-3 text-sm text-destructive">{submitError}</p>}
        {result && <DecisionCard result={result} />}
      </section>

      <section className="rounded-xl border border-border bg-card shadow-sm p-5">
        <h2 className="font-medium text-card-foreground">Your claims</h2>
        <form onSubmit={handleSearch} className="mt-3 flex flex-wrap gap-2">
          <input
            value={policyNumber}
            onChange={(e) => setPolicyNumber(e.target.value)}
            placeholder="Policy number, e.g. KHA-SIL-004512"
            className="min-w-[16rem] flex-1 rounded-md border border-border bg-background px-3 py-2 text-sm outline-none focus:border-primary"
          />
          <button
            type="submit"
            disabled={searching}
            className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:opacity-90 disabled:opacity-50"
          >
            {searching ? "Searching…" : "Find claims"}
          </button>
        </form>
        {searchError && <p className="mt-3 text-sm text-destructive">{searchError}</p>}
        {claims !== null && (
          <div className="mt-4 flex flex-col gap-3">
            {claims.length === 0 && <p className="text-sm text-muted-foreground">No claims found for this policy number.</p>}
            {claims.map((claim) => (
              <ClaimSummaryCard key={claim.claim_id} claim={claim} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function Progress({ label, state }: { label: string; state: "pending" | "active" | "done" }) {
  const style = state === "done" ? "bg-success/10 text-success" : state === "active" ? "animate-pulse bg-chart-1/10 text-chart-1" : "bg-muted text-muted-foreground";
  return <li className={`rounded-full px-3 py-1 font-medium ${style}`}>{state === "done" ? "✓ " : ""}{label}</li>;
}

const OUTCOME_TEXT: Record<string, string> = {
  paid: "Approved and paid to your registered bank account.",
  pending_human: "Your claim is with a claims officer for a decision. The assessment below is the recommendation they will review.",
  needs_resubmission: "A required document is missing or unreadable. Please upload it and resubmit.",
};

function DecisionCard({ result }: { result: SubmitClaimResult }) {
  const deductions = result.deductions ?? [];
  return (
    <div className="mt-5 rounded-md border border-border bg-secondary p-4 text-sm">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-mono text-xs text-muted-foreground">{result.claim_id}</span>
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusStyle(result.final_state)}`}>{humanizeStatus(result.final_state)}</span>
      </div>
      <p className="mt-2 font-medium text-card-foreground">{OUTCOME_TEXT[result.final_state] ?? humanizeStatus(result.final_state)}</p>
      {result.payable_amount != null && (
        <p className="mt-2 text-2xl font-semibold tabular-nums text-card-foreground">{formatInr(result.payable_amount)}</p>
      )}
      {deductions.length > 0 && (
        <div className="mt-3">
          <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Deductions</p>
          <ul className="mt-1 flex flex-col gap-1">
            {deductions.map((d, i) => (
              <li key={i} className="flex flex-wrap justify-between gap-2 tabular-nums">
                <span className="text-card-foreground">
                  {d.reason} <span className="font-mono text-xs text-muted-foreground">· policy clause {d.clause_id}</span>
                </span>
                <span className="text-destructive">−{formatInr(d.amount)}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {result.explanation && <p className="mt-3 border-l-2 border-border pl-3 text-muted-foreground">{result.explanation}</p>}
    </div>
  );
}

function ClaimSummaryCard({ claim }: { claim: ClaimSummary }) {
  return (
    <div className="rounded-md border border-border p-4 text-sm">
      <div className="flex items-center justify-between">
        <span className="font-medium text-card-foreground">{claim.claim_id}</span>
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusStyle(claim.status)}`}>{humanizeStatus(claim.status)}</span>
      </div>
      <p className="mt-1 text-muted-foreground">{claim.stated_illness}</p>
      <p className="mt-1 text-xs tabular-nums text-muted-foreground">
        Claimed {formatInr(claim.claimed_amount)}
        {claim.assessment?.payable_amount != null && ` · Payable ${formatInr(claim.assessment.payable_amount)}`}
      </p>
    </div>
  );
}
