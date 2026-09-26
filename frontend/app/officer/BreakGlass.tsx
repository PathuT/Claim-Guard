"use client";

import { useState } from "react";
import { ApiError, type BreakGlassResult, breakGlassDischargeSummary } from "@/lib/api";

/** security-matrix.md §9: "claims_officer ... open full discharge summary
 * via audited break-glass (reason required)". Collapsed by default — the
 * officer normally only needs medical_reviewer's structured
 * notes_for_officer (shown above in OfficerDetail), never the raw text;
 * this is the deliberate, logged exception path, not the default view. */
export function BreakGlass({ claimId, officerId }: { claimId: string; officerId: string }) {
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<BreakGlassResult | null>(null);

  async function handleOpen(e: React.FormEvent) {
    e.preventDefault();
    if (!officerId.trim()) {
      setError("Enter your officer ID above first.");
      return;
    }
    if (!reason.trim()) {
      setError("A reason is required to open the full discharge summary.");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const r = await breakGlassDischargeSummary(claimId, officerId.trim(), reason.trim());
      setResult(r);
    } catch (err) {
      setError(err instanceof ApiError ? `${err.message}${err.reasonCode ? ` (${err.reasonCode})` : ""}` : "Something went wrong.");
    } finally {
      setLoading(false);
    }
  }

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="self-start rounded-md border border-amber-300 bg-amber-50 px-3 py-1.5 text-xs font-medium text-amber-800 hover:bg-amber-100"
      >
        Open full discharge summary (break-glass)
      </button>
    );
  }

  return (
    <div className="rounded-md border border-amber-300 bg-amber-50 p-4">
      <p className="text-xs text-amber-800">
        This bypasses the normal restriction (only the medical reviewer agent reads raw medical text) and is
        permanently recorded in the compliance audit log under your officer ID and stated reason.
      </p>
      {!result ? (
        <form onSubmit={handleOpen} className="mt-3 flex flex-col gap-2">
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            placeholder="Reason for opening the full discharge summary (required)"
            className="rounded-md border border-amber-300 bg-white px-2 py-1 text-sm"
          />
          {error && <p className="text-sm text-red-600">{error}</p>}
          <div className="flex gap-2">
            <button
              type="submit"
              disabled={loading}
              className="rounded-md bg-amber-800 px-3 py-1.5 text-xs font-medium text-white hover:bg-amber-900 disabled:opacity-50"
            >
              {loading ? "Opening…" : "Confirm and open"}
            </button>
            <button type="button" onClick={() => setOpen(false)} className="text-xs text-amber-700 hover:underline">
              Cancel
            </button>
          </div>
        </form>
      ) : (
        <div className="mt-3">
          <p className="whitespace-pre-wrap rounded-md bg-white p-3 text-sm text-slate-800">{result.discharge_summary_text}</p>
          <p className="mt-2 text-xs text-amber-700">Recorded — audit trace {result.audit_trace_id}</p>
        </div>
      )}
    </div>
  );
}
