"use client";

import useSWR from "swr";
import { type SystemFacts, getSystemFacts } from "@/lib/api";

/** The live system facts (GET /system/facts), shared by every page that
 * states a figure about the system, so no number is typed into the UI. */
export function useSystemFacts() {
  return useSWR<SystemFacts>("system-facts", getSystemFacts, { refreshInterval: 30_000 });
}

/** A figure from the live facts: a skeleton while loading, "—" if the
 * backend can't compute it. */
export function Fact({ value, className = "" }: { value: string | number | null | undefined; className?: string }) {
  if (value === undefined) return <span className={`inline-block h-[1em] w-10 animate-pulse rounded bg-muted-foreground/20 align-middle ${className}`} />;
  return <span className={className}>{value === null ? "—" : value}</span>;
}

export function pct(part: number, whole: number): string {
  return whole ? `${Math.round((part / whole) * 100)}%` : "—";
}

export function ranAt(iso: string | null | undefined): string {
  if (!iso) return "";
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? "" : date.toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}
