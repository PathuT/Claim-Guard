"use client";

import { useState } from "react";
import {
  ApiError,
  type ClaimSummary,
  type SubmitClaimResult,
  listClaims,
  submitClaim,
} from "@/lib/api";
import { formatInr, humanizeStatus, statusStyle } from "@/lib/format";
import { DEMO_SCENARIOS } from "@/lib/demoScenarios";

export default function PolicyholderPage() {
  const [policyNumber, setPolicyNumber] = useState("");
  const [claims, setClaims] = useState<ClaimSummary[] | null>(null);
  const [searchError, setSearchError] = useState<string | null>(null);
  const [searching, setSearching] = useState(false);

  const [claimIdToSubmit, setClaimIdToSubmit] = useState("");
  const [submitResult, setSubmitResult] = useState<SubmitClaimResult | null>(null);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  async function handleSearch(e: React.FormEvent) {
    e.preventDefault();
    if (!policyNumber.trim()) return;
    setSearching(true);
    setSearchError(null);
    try {
      const result = await listClaims({ policyNumber: policyNumber.trim() });
      setClaims(result.claims);
    } catch (err) {
      setSearchError(err instanceof ApiError ? err.message : "Something went wrong.");
      setClaims(null);
    } finally {
      setSearching(false);
    }
  }

  async function submit(claimId: string) {
    if (!claimId.trim()) return;
    setSubmitting(true);
    setSubmitError(null);
    setSubmitResult(null);
    try {
      const result = await submitClaim(claimId.trim());
      setSubmitResult(result);
    } catch (err) {
      setSubmitError(err instanceof ApiError ? err.message : "Something went wrong.");
    } finally {
      setSubmitting(false);
    }
  }

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    submit(claimIdToSubmit);
  }

  function handleDemoClick(claimId: string) {
    setClaimIdToSubmit(claimId);
    submit(claimId);
  }

  return (
    <div className="flex flex-col gap-8">
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Policyholder</h1>
        <p className="mt-1 text-sm text-slate-600">
          Submit a claim by its claim_id, or look up your existing claims by policy number.
        </p>
      </div>

      <section className="rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="font-medium text-slate-900">Demo scenarios</h2>
        <p className="mt-1 text-xs text-slate-500">
          One click submits a real, already-seeded claim demonstrating a specific agent/governance behaviour.
        </p>
        <div className="mt-3 grid gap-2 sm:grid-cols-2">
          {DEMO_SCENARIOS.map((scenario) => (
            <button
              key={scenario.id}
              type="button"
              onClick={() => handleDemoClick(scenario.claimId)}
              disabled={submitting}
              className="flex flex-col items-start gap-0.5 rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-left transition-colors hover:border-slate-400 hover:bg-white disabled:opacity-50"
            >
              <span className="text-sm font-medium text-slate-900">{scenario.label}</span>
              <span className="text-xs text-slate-500">{scenario.description}</span>
            </button>
          ))}
        </div>
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="font-medium text-slate-900">Submit a claim</h2>
        <form onSubmit={handleSubmit} className="mt-3 flex gap-2">
          <input
            value={claimIdToSubmit}
            onChange={(e) => setClaimIdToSubmit(e.target.value)}
            placeholder="e.g. CLM-2026-018833"
            className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500"
          />
          <button
            type="submit"
            disabled={submitting}
            className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-700 disabled:opacity-50"
          >
            {submitting ? "Submitting…" : "Submit"}
          </button>
        </form>
        {submitError && <p className="mt-3 text-sm text-red-600">{submitError}</p>}
        {submitResult && <SubmitResultCard result={submitResult} />}
      </section>

      <section className="rounded-lg border border-slate-200 bg-white p-5">
        <h2 className="font-medium text-slate-900">Find your claims</h2>
        <form onSubmit={handleSearch} className="mt-3 flex gap-2">
          <input
            value={policyNumber}
            onChange={(e) => setPolicyNumber(e.target.value)}
            placeholder="e.g. KHA-SIL-004512"
            className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm outline-none focus:border-slate-500"
          />
          <button
            type="submit"
            disabled={searching}
            className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-slate-700 disabled:opacity-50"
          >
            {searching ? "Searching…" : "Search"}
          </button>
        </form>
        {searchError && <p className="mt-3 text-sm text-red-600">{searchError}</p>}
        {claims !== null && (
          <div className="mt-4 flex flex-col gap-3">
            {claims.length === 0 && <p className="text-sm text-slate-500">No claims found for this policy number.</p>}
            {claims.map((claim) => (
              <ClaimSummaryCard key={claim.claim_id} claim={claim} />
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function SubmitResultCard({ result }: { result: SubmitClaimResult }) {
  return (
    <div className="mt-4 rounded-md border border-slate-200 bg-slate-50 p-4 text-sm">
      <div className="flex items-center justify-between">
        <span className="font-medium">{result.claim_id}</span>
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusStyle(result.final_state)}`}>
          {humanizeStatus(result.final_state)}
        </span>
      </div>
      {result.payable_amount != null && (
        <p className="mt-2 text-slate-700">Payable amount: {formatInr(result.payable_amount)}</p>
      )}
      {result.explanation && <p className="mt-1 text-slate-600">{result.explanation}</p>}
      {result.flags && result.flags.length > 0 && (
        <p className="mt-1 text-xs text-slate-500">Flags: {result.flags.join(", ")}</p>
      )}
    </div>
  );
}

function ClaimSummaryCard({ claim }: { claim: ClaimSummary }) {
  return (
    <div className="rounded-md border border-slate-200 p-4 text-sm">
      <div className="flex items-center justify-between">
        <span className="font-medium">{claim.claim_id}</span>
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusStyle(claim.status)}`}>
          {humanizeStatus(claim.status)}
        </span>
      </div>
      <p className="mt-1 text-slate-600">{claim.stated_illness}</p>
      <p className="mt-1 text-xs text-slate-500">
        Claimed {formatInr(claim.claimed_amount)}
        {claim.assessment?.payable_amount != null && ` · Payable ${formatInr(claim.assessment.payable_amount)}`}
      </p>
    </div>
  );
}
