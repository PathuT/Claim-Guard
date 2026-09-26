"use client";

import { useState } from "react";
import { ApiError, type NewClaimResult, submitNewClaim } from "@/lib/api";

/** The real business-process entrypoint (docs/use-case.md §1: "Claim
 * submission: member, hospital, admission/discharge dates, stated illness,
 * claimed amount, documents") — a policyholder attaches two actual PDF
 * files here, which the backend genuinely extracts text from via pypdf
 * (backend/api/claim_intake.py), not a pre-seeded claim_id replay. This is
 * the one component in the Console that accepts real file uploads. */
export function NewClaimForm({ onCreated }: { onCreated: (claimId: string) => void }) {
  const [policyNumber, setPolicyNumber] = useState("");
  const [memberId, setMemberId] = useState("");
  const [hospitalId, setHospitalId] = useState("");
  const [admissionDate, setAdmissionDate] = useState("");
  const [dischargeDate, setDischargeDate] = useState("");
  const [statedIllness, setStatedIllness] = useState("");
  const [claimedAmount, setClaimedAmount] = useState("");
  const [finalBill, setFinalBill] = useState<File | null>(null);
  const [dischargeSummary, setDischargeSummary] = useState<File | null>(null);

  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<NewClaimResult | null>(null);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (!finalBill || !dischargeSummary) {
      setError("Attach both the final bill and discharge summary PDFs.");
      return;
    }
    setSubmitting(true);
    setError(null);
    setResult(null);
    try {
      const r = await submitNewClaim({
        policyNumber: policyNumber.trim(),
        memberId: memberId.trim(),
        hospitalId: hospitalId.trim(),
        admissionDate,
        dischargeDate,
        statedIllness: statedIllness.trim(),
        claimedAmount: Number(claimedAmount),
        finalBill,
        dischargeSummary,
      });
      setResult(r);
      onCreated(r.claim_id);
    } catch (err) {
      setError(err instanceof ApiError ? `${err.message}${err.reasonCode ? ` (${err.reasonCode})` : ""}` : "Something went wrong.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <form onSubmit={handleSubmit} className="mt-3 flex flex-col gap-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm">
          Policy number
          <input
            value={policyNumber}
            onChange={(e) => setPolicyNumber(e.target.value)}
            placeholder="e.g. KHA-SIL-004512"
            required
            className="rounded-md border border-border bg-background px-3 py-2 outline-none focus:border-primary"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Member ID
          <input
            value={memberId}
            onChange={(e) => setMemberId(e.target.value)}
            placeholder="e.g. MEM-004512-01"
            required
            className="rounded-md border border-border bg-background px-3 py-2 outline-none focus:border-primary"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Hospital ID
          <input
            value={hospitalId}
            onChange={(e) => setHospitalId(e.target.value)}
            placeholder="e.g. HOSP-001"
            required
            className="rounded-md border border-border bg-background px-3 py-2 outline-none focus:border-primary"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Claimed amount (₹)
          <input
            type="number"
            value={claimedAmount}
            onChange={(e) => setClaimedAmount(e.target.value)}
            placeholder="e.g. 18000"
            required
            className="rounded-md border border-border bg-background px-3 py-2 tabular-nums outline-none focus:border-primary"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Admission date
          <input
            type="date"
            value={admissionDate}
            onChange={(e) => setAdmissionDate(e.target.value)}
            required
            className="rounded-md border border-border bg-background px-3 py-2 outline-none focus:border-primary"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Discharge date
          <input
            type="date"
            value={dischargeDate}
            onChange={(e) => setDischargeDate(e.target.value)}
            required
            className="rounded-md border border-border bg-background px-3 py-2 outline-none focus:border-primary"
          />
        </label>
      </div>

      <label className="flex flex-col gap-1 text-sm">
        Stated illness
        <input
          value={statedIllness}
          onChange={(e) => setStatedIllness(e.target.value)}
          placeholder="e.g. Acute bronchitis"
          required
          className="rounded-md border border-border bg-background px-3 py-2 outline-none focus:border-primary"
        />
      </label>

      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1 text-sm">
          Final bill (PDF)
          <input
            type="file"
            accept="application/pdf"
            onChange={(e) => setFinalBill(e.target.files?.[0] ?? null)}
            required
            className="rounded-md border border-border bg-background px-3 py-2 text-xs file:mr-2 file:rounded file:border-0 file:bg-secondary file:px-2 file:py-1 file:text-xs"
          />
        </label>
        <label className="flex flex-col gap-1 text-sm">
          Discharge summary (PDF)
          <input
            type="file"
            accept="application/pdf"
            onChange={(e) => setDischargeSummary(e.target.files?.[0] ?? null)}
            required
            className="rounded-md border border-border bg-background px-3 py-2 text-xs file:mr-2 file:rounded file:border-0 file:bg-secondary file:px-2 file:py-1 file:text-xs"
          />
        </label>
      </div>

      {error && <p className="text-sm text-destructive">{error}</p>}
      {result && (
        <p className="text-sm text-success">
          Claim {result.claim_id} created (status: {result.status}). Submitting it for assessment now…
        </p>
      )}

      <button
        type="submit"
        disabled={submitting}
        className="self-start rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:opacity-90 disabled:opacity-50"
      >
        {submitting ? "Uploading…" : "Submit new claim"}
      </button>
    </form>
  );
}
