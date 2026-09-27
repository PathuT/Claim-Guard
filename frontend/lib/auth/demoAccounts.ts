import type { Role } from "./roles";

/** The demo accounts listed on the sign-in page (synthetic people only). */
export const DEMO_ACCOUNTS: { name: string; email: string; password: string; role: Role; blurb: string }[] = [
  { name: "Platform Admin", email: "admin@kaveri-health.example", password: "Admin@2026", role: "platform_admin", blurb: "Everything: the presenter account" },
  { name: "Arjun Mehta", email: "arjun.mehta@kaveri-health.example", password: "Officer@2026", role: "claims_officer", blurb: "Review queue, Live Run, pipeline" },
  { name: "Divya Nair", email: "divya.nair@kaveri-health.example", password: "Comply@2026", role: "compliance_officer", blurb: "Audit log, kill switch, architecture" },
  { name: "Priya Raman", email: "priya.raman@example.com", password: "Priya@2026", role: "policyholder", blurb: "Submit and track her own claims" },
];
