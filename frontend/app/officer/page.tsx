"use client";

import { useState } from "react";
import useSWR from "swr";
import { ApiError, listClaims } from "@/lib/api";
import { formatInr } from "@/lib/format";
import { OfficerDetail } from "./OfficerDetail";

const QUEUE_KEY = ["officer-queue", "pending_human"] as const;

export default function OfficerPage() {
  const [officerId, setOfficerId] = useState("");
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
      <div>
        <h1 className="text-xl font-semibold tracking-tight">Officer — T3 human review queue</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Every claim below is stuck at <code className="rounded bg-muted px-1">pending_human</code> — the
          supervisor cannot decide these itself (docs/architecture.md §8: only an officer creates a rejection or
          approves a fraud-flagged/high-value payout).
        </p>
        <label className="mt-3 flex max-w-sm flex-col gap-1 text-sm">
          Your officer ID (recorded on every decision)
          <input
            value={officerId}
            onChange={(e) => setOfficerId(e.target.value)}
            placeholder="e.g. officer-arjun"
            className="rounded-md border border-border bg-background px-3 py-2 focus:border-primary outline-none"
          />
        </label>
      </div>

      {loading && <p className="text-sm text-muted-foreground">Loading queue…</p>}
      {loadError && <p className="text-sm text-destructive">{loadError}</p>}
      {!loading && !loadError && queue.length === 0 && (
        <p className="text-sm text-muted-foreground">Nothing in the queue right now.</p>
      )}

      <div className="flex flex-col gap-3">
        {queue.map((claim) => (
          <div key={claim.claim_id} className="rounded-lg border border-border bg-card p-5">
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
