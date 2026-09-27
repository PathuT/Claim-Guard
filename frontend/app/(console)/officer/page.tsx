"use client";

import { useState } from "react";
import useSWR from "swr";
import { ApiError, listClaims } from "@/lib/api";
import { PageHeader } from "@/app/_components/PageHeader";
import { useSessionUser } from "@/app/_components/SessionContext";
import { formatInr } from "@/lib/format";
import { OfficerDetail } from "./OfficerDetail";

const QUEUE_KEY = ["officer-queue", "pending_human"] as const;

export default function OfficerPage() {
  const user = useSessionUser();
  // Decisions are recorded against the signed-in user, not a typed-in id.
  const officerId = user?.actorId ?? "officer-arjun";
  const [selected, setSelected] = useState<string | null>(null);

  const { data, error, isLoading, mutate } = useSWR(QUEUE_KEY, () => listClaims({ status: "pending_human" }));
  const queue = data?.claims ?? [];
  const loading = isLoading;
  const loadError = error ? (error instanceof ApiError ? error.message : "Something went wrong.") : null;

  function handleDecided() {
    setSelected(null);
    mutate();
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        eyebrow="Human in the loop · T3"
        title="Review queue"
        description={
          <>
            The workflow routed each claim below to a human: above ₹50,000, a fraud flag, an exclusion or waiting period, or a
            recommended rejection. Agents can only recommend. Only an officer decision can approve these payouts (PAY-003 /
            PAY-004) or reject a claim (STATE-001). You see coded findings, flags and clauses, not raw medical text; reading the
            discharge summary needs an audited break-glass with a reason.
          </>
        }
        actions={
          <span className="rounded-lg border border-border bg-card px-3 py-2 text-xs text-muted-foreground shadow-sm">
            Decisions recorded as <span className="font-mono font-semibold text-card-foreground">{officerId}</span>
          </span>
        }
      />

      {loading && <p className="text-sm text-muted-foreground">Loading queue…</p>}
      {loadError && <p className="text-sm text-destructive">{loadError}</p>}
      {!loading && !loadError && queue.length === 0 && (
        <p className="text-sm text-muted-foreground">Nothing in the queue right now.</p>
      )}

      <div className="flex flex-col gap-3">
        {queue.map((claim) => (
          <div key={claim.claim_id} className="rounded-xl border border-border bg-card shadow-sm p-5">
            <button
              type="button"
              onClick={() => setSelected(selected === claim.claim_id ? null : claim.claim_id)}
              className="flex w-full items-center justify-between text-left"
            >
              <div>
                <span className="font-medium text-card-foreground">{claim.claim_id}</span>
                <span className="ml-3 text-sm text-muted-foreground">{claim.stated_illness}</span>
              </div>
              <span className="text-sm tabular-nums text-muted-foreground">
                {formatInr(claim.claimed_amount)} {selected === claim.claim_id ? "▲" : "▼"}
              </span>
            </button>
            {selected === claim.claim_id && (
              <div className="mt-4">
                <OfficerDetail claimId={claim.claim_id} officerId={officerId} onDecided={handleDecided} />
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}
