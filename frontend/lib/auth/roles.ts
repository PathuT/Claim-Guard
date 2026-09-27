/** Console roles and which pages each may open. Shared by proxy.ts (the
 * route guard), the sign-in action and the sidebar, so the rule lives in one
 * place — the same single-source-of-truth idea as the agents' security
 * matrix, applied to the humans using the console. */

export type Role = "platform_admin" | "claims_officer" | "compliance_officer" | "policyholder";

export const ROLE_LABEL: Record<Role, string> = {
  platform_admin: "Platform admin",
  claims_officer: "Claims officer",
  compliance_officer: "Compliance officer",
  policyholder: "Policyholder",
};

/** Page prefix -> roles allowed to open it. "/" (the dashboard) is open to every signed-in user. */
export const ROUTE_ACCESS: { prefix: string; roles: Role[] }[] = [
  { prefix: "/live", roles: ["platform_admin", "claims_officer"] },
  { prefix: "/problem", roles: ["platform_admin", "claims_officer", "compliance_officer"] },
  { prefix: "/architecture", roles: ["platform_admin", "claims_officer", "compliance_officer"] },
  { prefix: "/officer", roles: ["platform_admin", "claims_officer"] },
  { prefix: "/compliance", roles: ["platform_admin", "compliance_officer"] },
  { prefix: "/pipeline", roles: ["platform_admin", "claims_officer", "compliance_officer"] },
  { prefix: "/policyholder", roles: ["platform_admin", "policyholder"] },
];

export function canAccess(role: Role, pathname: string): boolean {
  const rule = ROUTE_ACCESS.find((r) => pathname === r.prefix || pathname.startsWith(`${r.prefix}/`));
  return rule ? rule.roles.includes(role) : true;
}

/** Where each role lands after signing in. */
export const HOME_FOR_ROLE: Record<Role, string> = {
  platform_admin: "/",
  claims_officer: "/officer",
  compliance_officer: "/compliance",
  policyholder: "/policyholder",
};

export interface NavItem {
  href: string;
  label: string;
  icon: string;
  description: string;
  external?: boolean;
}

export const NAV_SECTIONS: { title: string; items: NavItem[] }[] = [
  {
    title: "Overview",
    items: [
      { href: "/", label: "Dashboard", icon: "home", description: "Live status of claims, governance and evaluation" },
      { href: "/problem", label: "Business problem", icon: "alert", description: "Why claims need automation, and why automation needs governance" },
      { href: "/architecture", label: "Architecture", icon: "layers", description: "The brief, the design and the decisions" },
    ],
  },
  {
    title: "Demo",
    items: [{ href: "/live", label: "Live Run", icon: "play", description: "Upload PDFs and watch the agents work" }],
  },
  {
    title: "Operations",
    items: [
      { href: "/policyholder", label: "Submit a claim", icon: "upload", description: "Policyholder view" },
      { href: "/officer", label: "Review queue", icon: "inbox", description: "Claims waiting for a human decision" },
      { href: "/compliance", label: "Compliance", icon: "shield", description: "Audit log, denials and the payout kill switch" },
      { href: "/pipeline", label: "Agent pipeline", icon: "workflow", description: "Each workflow step's output for a claim" },
    ],
  },
  {
    title: "Observability",
    items: [
      { href: "/live#evals", label: "Harbor evals", icon: "check", description: "Scenario suite and per-claim checks" },
      { href: "http://localhost:6006", label: "Phoenix traces", icon: "activity", description: "One OpenTelemetry trace per claim", external: true },
    ],
  },
];

export function visibleNav(role: Role) {
  return NAV_SECTIONS.map((section) => ({
    ...section,
    items: section.items.filter((item) => item.external ? role === "platform_admin" || role === "compliance_officer" : canAccess(role, item.href.split("#")[0])),
  })).filter((section) => section.items.length > 0);
}
