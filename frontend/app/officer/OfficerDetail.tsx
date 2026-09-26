"use client";

import { useState } from "react";
import useSWR from "swr";
import {
  ApiError,
  type OfficerDecisionResult,
  getClaimForReview,
  submitOfficerDecision,
} from "@/lib/api";
import { formatInr, severityStyle } from "@/lib/format";
import { BreakGlass } from "./BreakGlass";

// STATE-002 (governance/rules.py) enforces the exact required step names
// for an approved/paid transition: "medical_review", "coverage_assessment",
// "fraud_screen" — NOT the agent names themselves ("intake"/"coverage"/
// "fraud"). Confirmed live: an earlier version of this used the agent
// names and every approval was denied with reason_code STATE-002 ("skips
// required steps"), caught only by actually submitting a real decision
// through the running API, not by reading api/state_machine.py's own
// (misleadingly incomplete) REQUIRED_STEPS_FOR_TRANSITION comment.
const REQUIRED_COMPLETED_STEPS = ["medical_review", "coverage_assessment", "fraud_screen"];

export function OfficerDetail({ claimId, officerId, onDecided }: { claimId: string; officerId: string; onDecided: () => void }) {
  const { data: review, error, isLoading: loading } = useSWR(["officer-review", claimId], () => getClaimForReview(claimId));
  const loadError = error ? (error instanceof ApiError ? error.message : "Something went wrong.") : null;

  const [decision, setDecision] = useState<"approved" | "approved_partial" | "rejected">("approved");
  // null = "not yet touched by the officer" — the assessed payable amount
  // is then used as the displayed/submitted default, computed at render
  // time rather than synced in via an effect (React's own guidance: derive
  // during render instead of "setState to mirror a prop/data value" —
  // https://react.dev/learn/you-might-not-need-an-effect).
  const [payoutAmountOverride, setPayoutAmountOverride] = useState<string | null>(null);
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [result, setResult] = useState<OfficerDecisionResult | null>(null);

  const payoutAmount = payoutAmountOverride ?? String(review?.assessment?.payable_amount ?? 0);

  async function handleDecide(e: React.FormEvent) {
    e.preventDefault();
    if (!review) return;
    if (!officerId.trim()) {
      setSubmitError("Enter your officer ID above before recording a decision.");
      return;
    }
    if (!reason.trim()) {
      setSubmitError("A reason is required for every decision (IRDAI clear-reasons requirement).");
      return;
    }
    setSubmitting(true);
    setSubmitError(null);
    try {
      const isPayout = decision === "approved" || decision === "approved_partial";
      const r = await submitOfficerDecision({
        claim_id: review.claim_id,
        officer_id: officerId.trim(),
        decision,
        completed_steps: REQUIRED_COMPLETED_STEPS,
        reason: reason.trim(),
        payout_amount: isPayout ? Number(payoutAmount) : undefined,
        registered_account_ref: isPayout ? review.registered_account_ref : undefined,
        remaining_sum_insured: isPayout ? review.remaining_sum_insured : undefined,
        fraud_flags: review.assessment?.fraud_flags.map((f) => f.type),
      });
      setResult(r);
      onDecided();
    } catch (err) {
      setSubmitError(err instanceof ApiError ? `${err.message}${err.reasonCode ? ` (${err.reasonCode})` : ""}` : "Something went wrong.");
    } finally {
      setSubmitting(false);
    }
  }

  if (loading) return <p className="text-sm text-slate-500">Loading claim…</p>;
  if (loadError) return <p className="text-sm text-red-600">{loadError}</p>;
  if (!review) return null;

  const assessment = review.assessment;
  const finding = assessment?.medical_finding;

  return (
    <div className="flex flex-col gap-4 border-t border-slate-200 pt-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Claim</h3>
          <p className="mt-1 text-sm text-slate-700">{review.stated_illness}</p>
          <p className="mt-1 text-sm text-slate-500">Claimed: {formatInr(review.claimed_amount)}</p>
          {assessment && <p className="text-sm text-slate-500">Assessed payable: {formatInr(assessment.payable_amount)}</p>}
          <p className="text-sm text-slate-500">Remaining sum insured: {formatInr(review.remaining_sum_insured)}</p>
        </div>
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Flags</h3>
          {assessment && assessment.flags.length > 0 ? (
            <ul className="mt-1 flex flex-wrap gap-1">
              {assessment.flags.map((f) => (
                <li key={f} className="rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
                  {f}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-1 text-sm text-slate-400">None</p>
          )}
        </div>
      </div>

      {assessment && assessment.deductions.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Deductions (clause references)</h3>
          <ul className="mt-1 flex flex-col gap-1 text-sm text-slate-700">
            {assessment.deductions.map((d, i) => (
              <li key={i}>
                {formatInr(d.amount)} — {d.reason} <span className="text-slate-400">({d.clause_id})</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {assessment && assessment.fraud_flags.length > 0 && (
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Fraud signals</h3>
          <ul className="mt-1 flex flex-col gap-1">
            {assessment.fraud_flags.map((f, i) => (
              <li key={i} className="flex items-center gap-2 text-sm">
                <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${severityStyle(f.severity)}`}>{f.severity}</span>
                {f.type}
                <span className="text-xs text-slate-400">evidence: {f.evidence_ref}</span>
              </li>
            ))}
          </ul>
        </div>
      )}

      {finding && (
        <div>
          <h3 className="text-xs font-semibold uppercase tracking-wide text-slate-500">Medical reviewer&apos;s note</h3>
          <p className="mt-1 rounded-md bg-slate-50 p-3 text-sm text-slate-700">{finding.notes_for_officer}</p>
          <p className="mt-1 text-xs text-slate-400">
            ICD-10: {finding.icd10} · confidence {(finding.confidence * 100).toFixed(0)}%
          </p>
        </div>
      )}

      <BreakGlass claimId={claimId} officerId={officerId} />

      <form onSubmit={handleDecide} className="mt-2 flex flex-col gap-3 rounded-md border border-slate-200 bg-slate-50 p-4">
        <h3 className="text-sm font-medium text-slate-900">Record decision</h3>
        <div className="flex gap-4 text-sm">
          {(["approved", "approved_partial", "rejected"] as const).map((d) => (
            <label key={d} className="flex items-center gap-1.5">
              <input type="radio" name="decision" checked={decision === d} onChange={() => setDecision(d)} />
              {d.replace(/_/g, " ")}
            </label>
          ))}
        </div>
        {(decision === "approved" || decision === "approved_partial") && (
          <label className="flex flex-col gap-1 text-sm">
            Payout amount
            <input
              type="number"
              value={payoutAmount}
              onChange={(e) => setPayoutAmountOverride(e.target.value)}
              className="w-40 rounded-md border border-slate-300 px-2 py-1"
            />
          </label>
        )}
        <label className="flex flex-col gap-1 text-sm">
          Reason (required)
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            className="rounded-md border border-slate-300 px-2 py-1"
            placeholder="e.g. Waiting period exception confirmed via call with policyholder."
          />
        </label>
        {submitError && <p className="text-sm text-red-600">{submitError}</p>}
        {result && (
          <p className="text-sm text-emerald-700">
            Decision recorded ({result.officer_decision_id}) — claim now {result.new_state.replace(/_/g, " ")}
            {result.payout_result && " — payout executed"}.
          </p>
        )}
        <button
          type="submit"
          disabled={submitting || !!result}
          className="self-start rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-700 disabled:opacity-50"
        >
          {submitting ? "Recording…" : "Submit decision"}
        </button>
      </form>
    </div>
  );
}
