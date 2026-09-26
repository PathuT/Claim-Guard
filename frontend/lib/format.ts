/** Small formatting helpers shared across the three Console role views. */

export function formatInr(amount: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(amount);
}

/** Tailwind class pairs for a claim's status pill — one place to keep the
 * status -> color mapping consistent across the policyholder/officer views. */
const STATUS_STYLES: Record<string, string> = {
  submitted: "bg-slate-100 text-slate-700",
  assessing: "bg-blue-100 text-blue-700",
  auto_approved: "bg-emerald-100 text-emerald-700",
  approved: "bg-emerald-100 text-emerald-700",
  approved_partial: "bg-amber-100 text-amber-700",
  paid: "bg-emerald-100 text-emerald-800",
  pending_human: "bg-amber-100 text-amber-800",
  rejected: "bg-red-100 text-red-700",
  needs_resubmission: "bg-red-100 text-red-700",
};

export function statusStyle(status: string): string {
  return STATUS_STYLES[status] ?? "bg-slate-100 text-slate-700";
}

const SEVERITY_STYLES: Record<string, string> = {
  low: "bg-slate-100 text-slate-700",
  medium: "bg-amber-100 text-amber-800",
  high: "bg-red-100 text-red-700",
};

export function severityStyle(severity: string): string {
  return SEVERITY_STYLES[severity.toLowerCase()] ?? "bg-slate-100 text-slate-700";
}

export function humanizeStatus(status: string): string {
  return status.replace(/_/g, " ");
}
