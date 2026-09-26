/**
 * ClaimGuard Console API client (M8, docs/plan.md).
 *
 * Every function here is a direct browser `fetch()` against a real,
 * locally-running backend service (AgentOS on :8000, the officer decision
 * API on :8400 — see the root .env / package.json's `dev:agentos`/
 * `dev:officer` scripts). There is no proxying Next.js route handler layer
 * and no server-side session: the whole project has no human-authentication
 * system (only agent-to-agent JWT/RBAC — see docs/security-matrix.md),
 * so the Console has nothing to attach a session to. This is a deliberate,
 * documented scope boundary (see the root README's Console section), not an
 * oversight — a real login system was out of scope for M8's "Done when: the
 * full S01 and S02 journeys work from the browser."
 *
 * Types below mirror backend/api/agentos.py and backend/api/officer.py's
 * actual Pydantic response models field-for-field, confirmed against live
 * responses during M7/M8 development — not guessed from the OpenAPI schema.
 */

const AGENTOS_URL = process.env.NEXT_PUBLIC_AGENTOS_URL ?? "http://localhost:8000";
const OFFICER_API_URL = process.env.NEXT_PUBLIC_OFFICER_API_URL ?? "http://localhost:8400";

export class ApiError extends Error {
  constructor(
    message: string,
    public status: number,
    public reasonCode?: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers: { "Content-Type": "application/json", ...init?.headers },
    });
  } catch {
    // A network-level failure (backend not running, wrong port, CORS
    // misconfigured) looks identical to the browser — surfaced as one
    // clear ApiError rather than an unhandled fetch rejection each caller
    // would need to catch differently.
    throw new ApiError(`Could not reach ${url} — is the backend running? (see package.json's dev:agentos/dev:officer scripts)`, 0);
  }

  if (!response.ok) {
    let detail: { reason_code?: string; message?: string } = {};
    try {
      const body = await response.json();
      detail = body?.detail ?? body;
    } catch {
      // non-JSON error body; fall through with the plain status
    }
    throw new ApiError(detail.message ?? response.statusText, response.status, detail.reason_code);
  }
  return response.json() as Promise<T>;
}

// --- Shared shapes (backend/api/agentos.py) ---

export interface Deduction {
  amount: number;
  reason: string;
  clause_id: string;
}

export interface FraudFlag {
  type: string;
  severity: string;
  evidence_ref: string;
}

export interface MedicalFinding {
  claim_id: string;
  icd10: string;
  diagnosis_category: string;
  length_of_stay_hours: number;
  stay_justified: boolean;
  day_care_procedure: boolean;
  pre_existing_suspected: boolean;
  excluded_treatment: boolean;
  accident_related: boolean;
  confidence: number;
  notes_for_officer: string;
}

export interface BillLineItem {
  label: string;
  amount: number;
}

export interface IntakeSummary {
  line_items: BillLineItem[];
  bill_total: number;
  admission_date: string;
  discharge_date: string;
  length_of_stay_hours: number;
}

export interface ClaimAssessment {
  claim_id: string;
  claimed_amount: number;
  deductions: Deduction[];
  co_pay_amount: number;
  payable_amount: number;
  recommended_decision: string;
  flags: string[];
  fraud_flags: FraudFlag[];
  medical_finding?: MedicalFinding;
  intake_summary?: IntakeSummary;
}

export interface ClaimStatus {
  claim_id: string;
  status: string;
  assessment: ClaimAssessment | null;
}

export interface ClaimSummary {
  claim_id: string;
  policy_number: string;
  member_id: string;
  status: string;
  claimed_amount: number;
  stated_illness: string;
  assessment: ClaimAssessment | null;
}

export interface AuditEntry {
  trace_id: string;
  timestamp: string;
  agent_id: string;
  tool_name: string;
  policy_verdict: string;
  violation_reason: string | null;
}

export interface SubmitClaimResult {
  claim_id: string;
  tier: string | null;
  final_state: string;
  payable_amount: number | null;
  deductions: Deduction[] | null;
  flags: string[] | null;
  fraud_flags: FraudFlag[] | null;
  explanation: string | null;
  payout_result: Record<string, unknown> | null;
}

// --- AgentOS API (:8000) ---

export function submitClaim(claimId: string): Promise<SubmitClaimResult> {
  return request(`${AGENTOS_URL}/claims`, {
    method: "POST",
    body: JSON.stringify({ claim_id: claimId }),
  });
}

export interface NewClaimFields {
  policyNumber: string;
  memberId: string;
  hospitalId: string;
  admissionDate: string;
  dischargeDate: string;
  statedIllness: string;
  claimedAmount: number;
  finalBill: File;
  dischargeSummary: File;
}

export interface NewClaimResult {
  claim_id: string;
  status: string;
  missing_documents: string[];
}

/** The real upload entrypoint (backend/api/claim_intake.py) — a
 * policyholder attaches two actual PDF files, extracted by real pypdf text
 * extraction, not a pre-seeded claim_id. multipart/form-data, so this one
 * call does NOT go through the shared `request()` helper's JSON
 * content-type default. */
export async function submitNewClaim(fields: NewClaimFields): Promise<NewClaimResult> {
  const form = new FormData();
  form.set("policy_number", fields.policyNumber);
  form.set("member_id", fields.memberId);
  form.set("hospital_id", fields.hospitalId);
  form.set("admission_date", fields.admissionDate);
  form.set("discharge_date", fields.dischargeDate);
  form.set("stated_illness", fields.statedIllness);
  form.set("claimed_amount", String(fields.claimedAmount));
  form.set("final_bill", fields.finalBill);
  form.set("discharge_summary", fields.dischargeSummary);

  let response: Response;
  try {
    response = await fetch(`${AGENTOS_URL}/claims/new`, { method: "POST", body: form });
  } catch {
    throw new ApiError(`Could not reach ${AGENTOS_URL} — is the backend running?`, 0);
  }
  if (!response.ok) {
    let detail: { reason_code?: string; message?: string } = {};
    try {
      detail = (await response.json())?.detail ?? {};
    } catch {
      // non-JSON error body
    }
    throw new ApiError(detail.message ?? response.statusText, response.status, detail.reason_code);
  }
  return response.json() as Promise<NewClaimResult>;
}

export function getClaimStatus(claimId: string): Promise<ClaimStatus> {
  return request(`${AGENTOS_URL}/claims/${encodeURIComponent(claimId)}`);
}

export function listClaims(filter: { policyNumber?: string; status?: string }): Promise<{ claims: ClaimSummary[] }> {
  const params = new URLSearchParams();
  if (filter.policyNumber) params.set("policy_number", filter.policyNumber);
  if (filter.status) params.set("status", filter.status);
  const qs = params.toString();
  return request(`${AGENTOS_URL}/claims${qs ? `?${qs}` : ""}`);
}

export function getClaimAudit(claimId: string): Promise<{ claim_id: string; entries: AuditEntry[] }> {
  return request(`${AGENTOS_URL}/claims/${encodeURIComponent(claimId)}/audit`);
}

export function getAuditLog(filter: { policyVerdict?: string; limit?: number }): Promise<{ entries: AuditEntry[] }> {
  const params = new URLSearchParams();
  if (filter.policyVerdict) params.set("policy_verdict", filter.policyVerdict);
  if (filter.limit) params.set("limit", String(filter.limit));
  const qs = params.toString();
  return request(`${AGENTOS_URL}/audit${qs ? `?${qs}` : ""}`);
}

// --- Officer Decision API (:8400) ---

export interface OfficerReview {
  claim_id: string;
  policy_number: string;
  status: string;
  claimed_amount: number;
  stated_illness: string;
  assessment: ClaimAssessment | null;
  registered_account_ref: string;
  remaining_sum_insured: number;
}

export function getClaimForReview(claimId: string): Promise<OfficerReview> {
  return request(`${OFFICER_API_URL}/claims/${encodeURIComponent(claimId)}/review`);
}

export interface BreakGlassResult {
  claim_id: string;
  discharge_summary_text: string;
  audit_trace_id: string;
}

/** security-matrix.md §9: "open full discharge summary via audited
 * break-glass (reason required)" — bypasses the normal medical_reviewer-
 * only restriction for a human officer, logged under a distinct
 * agent_id/tool_name in the same governance audit log the Compliance view
 * reads (see backend/api/officer.py's own endpoint docstring). */
export function breakGlassDischargeSummary(claimId: string, officerId: string, reason: string): Promise<BreakGlassResult> {
  return request(`${OFFICER_API_URL}/claims/${encodeURIComponent(claimId)}/break-glass/discharge-summary`, {
    method: "POST",
    body: JSON.stringify({ officer_id: officerId, reason }),
  });
}

export type OfficerDecisionType = "approved" | "approved_partial" | "rejected";

export interface OfficerDecisionRequest {
  claim_id: string;
  officer_id: string;
  decision: OfficerDecisionType;
  completed_steps: string[];
  reason: string;
  payout_amount?: number;
  registered_account_ref?: string;
  remaining_sum_insured?: number;
  fraud_flags?: string[];
  already_paid?: boolean;
}

export interface OfficerDecisionResult {
  claim_id: string;
  officer_decision_id: string;
  new_state: string;
  payout_result: Record<string, unknown> | null;
}

export function submitOfficerDecision(req: OfficerDecisionRequest): Promise<OfficerDecisionResult> {
  return request(`${OFFICER_API_URL}/decisions`, {
    method: "POST",
    body: JSON.stringify(req),
  });
}
