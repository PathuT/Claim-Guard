/** Small formatting helpers shared across the Console's role views. */

export function formatInr(amount: number): string {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    maximumFractionDigits: 0,
  }).format(amount);
}

/** Tailwind class pairs for a claim's status pill, built on the design
 * system's semantic tokens (--success/--warning/--destructive/--muted) —
 * never the brand --primary, which the design brief reserves for
 * buttons/active nav only, not status indicators. */
const STATUS_STYLES: Record<string, string> = {
  submitted: "bg-muted text-muted-foreground",
  assessing: "bg-chart-1/10 text-chart-1",
  auto_approved: "bg-success/10 text-success",
  approved: "bg-success/10 text-success",
  approved_partial: "bg-warning/10 text-warning",
  paid: "bg-success/10 text-success",
  pending_human: "bg-warning/10 text-warning",
  rejected: "bg-destructive/10 text-destructive",
  needs_resubmission: "bg-destructive/10 text-destructive",
};

export function statusStyle(status: string): string {
  return STATUS_STYLES[status] ?? "bg-muted text-muted-foreground";
}

const SEVERITY_STYLES: Record<string, string> = {
  low: "bg-muted text-muted-foreground",
  medium: "bg-warning/10 text-warning",
  high: "bg-destructive/10 text-destructive",
};

export function severityStyle(severity: string): string {
  return SEVERITY_STYLES[severity.toLowerCase()] ?? "bg-muted text-muted-foreground";
}

export function humanizeStatus(status: string): string {
  return status.replace(/_/g, " ");
}
