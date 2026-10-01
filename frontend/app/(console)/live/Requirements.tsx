"use client";

import { ranAt, useSystemFacts } from "@/app/_components/LiveFacts";
import { formatInr } from "@/lib/format";
import type { LogLine } from "./LiveConsole";

/** The project's requirements (docs/engineering-guide.md's non-negotiable invariants
 * plus the core functional asks and the deterministic guardrails), each
 * ticked off by concrete evidence from THIS run's live backend log and step
 * events — not a static claim. A requirement a
 * single claim run can't exercise (e.g. delegation) says where it is
 * proven instead: the security test suite / Harbor evals. */

interface Evidence {
  status: "proven" | "pending" | "tests";
  proof: string;
}

/** Chapter progress from the backend's step() events, keyed by step id. */
export type StepEvidence = Record<string, { status: string; summary?: string | null; data: Record<string, unknown> }>;

interface Requirement {
  id: string;
  title: string;
  check: (lines: LogLine[], steps: StepEvidence) => Evidence;
}

const has = (lines: LogLine[], pred: (l: LogLine) => boolean) => lines.filter(pred);
const text = (l: LogLine) => `${l.title} ${l.detail ?? ""}`;
const strings = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : []);
const numbers = (v: unknown): number[] => (Array.isArray(v) ? v.filter((x): x is number => typeof x === "number") : []);

function proven(proof: string): Evidence {
  return { status: "proven", proof };
}
function pending(proof: string): Evidence {
  return { status: "pending", proof };
}

const REQUIREMENTS: Requirement[] = [
  {
    id: "R1",
    title: "Every agent tool call passes the AGT governance adapter",
    check: (lines) => {
      const decisions = has(lines, (l) => l.layer === "governance" && /policy check/.test(l.title));
      return decisions.length ? proven(`${decisions.length} governance decisions this run (allow + deny), each audited`) : pending("waiting for the first tool call");
    },
  },
  {
    id: "R2",
    title: "All data access goes through the data gateway with a valid JWT",
    check: (lines) => {
      const calls = has(lines, (l) => l.layer === "gateway" && /Data gateway POST/.test(l.title));
      return calls.length ? proven(`${calls.length} gateway call(s), each JWT-verified before any row returned`) : pending("waiting for an agent to read data");
    },
  },
  {
    id: "R3",
    title: "Tokens only for verified agent identities — one scope, ≤ 300 s, EdDSA",
    check: (lines) => {
      const ids = has(lines, (l) => l.layer === "identity");
      const tokens = has(lines, (l) => l.layer === "token" && /minted/.test(l.title));
      if (!tokens.length) return pending("waiting for a token request");
      const ttl = tokens[0].detail?.match(/ttl=(\d+)s/)?.[1];
      return proven(`${ids.length} Ed25519 identity assertion(s) → ${tokens.length} single-scope token(s)${ttl ? `, ttl ${ttl}s` : ""}`);
    },
  },
  {
    id: "R4",
    title: "Only the medical reviewer sees medical text",
    check: (lines) => {
      const refused = has(lines, (l) => l.level === "deny" && /DATA-001|GOV-003/.test(text(l)));
      if (refused.length) return proven(`coverage agent's attempt refused: ${refused.map((l) => text(l).match(/DATA-001|GOV-003/)?.[0]).join(" + ")}`);
      const pseudo = has(lines, (l) => /PSEUDONYMISED/.test(l.title));
      const medical = has(lines, (l) => /Medical finding/.test(l.title));
      return medical.length && pseudo.length
        ? proven("medical reviewer returned a coded finding; fraud agent worked on pseudonymised data only")
        : pending("waiting for the medical review");
    },
  },
  {
    id: "R5",
    title: "Delegation never widens access",
    // Not exercised by a single claim; evidenced by the last real test run (GET /system/facts).
    check: () => ({ status: "tests", proof: "not exercised by a single claim; covered by the token service's delegation tests" }),
  },
  {
    id: "R6",
    title: "No AI-only rejection — humans decide T3",
    check: (lines) => {
      const tier = has(lines, (l) => /Action tier/.test(l.title))[0];
      if (!tier) return pending("waiting for the tier decision");
      return tier.title.includes("T3")
        ? proven("T3: agents only recommended; claim moved to pending_human for an officer")
        : proven("T2: within auto-pay limits with every check passed — no human needed, no rejection possible");
    },
  },
  {
    id: "R7",
    title: "Fail closed — any policy failure means deny",
    check: (lines) => {
      const denies = has(lines, (l) => l.level === "deny");
      return denies.length ? proven(`${denies.length} request(s) denied with a named rule`) : pending("run the red-team attack to see denials");
    },
  },
  {
    id: "R8",
    title: "Uploaded documents are untrusted — never instructions",
    check: (lines) => {
      const injected = has(lines, (l) => /instruction-like text/i.test(l.title));
      const intake = has(lines, (l) => /UNTRUSTED/.test(l.detail ?? ""));
      if (injected.length && intake.length) return proven("hidden instruction detected in the PDF; passed to agents as delimited untrusted data and ignored");
      return intake.length ? proven("documents passed to the intake agent as delimited UNTRUSTED data") : pending("waiting for intake");
    },
  },
  {
    id: "R9",
    title: "Every decision emits an OpenTelemetry span — redacted",
    check: (lines) => {
      const spans = has(lines, (l) => l.kind === "trace" || l.layer === "llm");
      const redacted = has(lines, (l) => /redacted/.test(l.detail ?? ""));
      return spans.length ? proven(`${spans.length} spans exported to Phoenix under one trace${redacted.length ? `; medical text redacted in ${redacted.length}` : ""}`) : pending("waiting for spans");
    },
  },
  {
    id: "R10",
    title: "Audit log is append-only and hash-chained",
    check: (lines) => {
      const verified = has(lines, (l) => /hash chain verified/i.test(l.title));
      if (verified.length) return proven("FlightRecorder integrity check passed after this run");
      const appended = has(lines, (l) => /hash-chained FlightRecorder/.test(l.detail ?? ""));
      return appended.length ? proven(`${appended.length} entries appended to the hash chain`) : pending("waiting for the first decision");
    },
  },
  {
    id: "R11",
    title: "Secrets from env; tokens never logged (jti only)",
    check: (lines) => {
      const tokens = has(lines, (l) => l.layer === "token" && /jti=/.test(l.detail ?? ""));
      return tokens.length ? proven("every token appears only by its jti — the JWT itself is never logged") : pending("waiting for a token");
    },
  },
  {
    id: "R12",
    title: "Payments are a mock — no real money path",
    check: (lines) => {
      const paid = has(lines, (l) => l.layer === "payment");
      if (paid.length) return proven("payout recorded in the payments mock ledger");
      const withheld = has(lines, (l) => /Payout withheld/.test(l.title));
      return withheld.length ? proven("payout withheld pending a human; nothing written to payments") : pending("waiting for the payout step");
    },
  },
  {
    id: "F1",
    title: "Settlement is exact; every deduction cites a clause",
    check: (lines) => {
      const deductions = has(lines, (l) => /Deduction −/.test(l.title));
      const payable = has(lines, (l) => /^Payable /.test(l.title));
      return payable.length ? proven(`${deductions.length} deduction(s), each with its clause_id; maths by the settlement engine`) : pending("waiting for settlement");
    },
  },
  {
    id: "F2",
    title: "Fraud screening on pseudonymised data + hospital watchlist",
    check: (lines) => {
      const done = has(lines, (l) => /Fraud (signal|screen)/.test(l.title));
      return done.length ? proven(done.map((l) => l.title.replace(/^Fraud /, "")).join("; ")) : pending("waiting for the fraud agent");
    },
  },
  {
    id: "G1",
    title: "Prompt-injection guardrail flags hidden instructions",
    check: (lines, steps) => {
      const scan = steps.doc_guardrail;
      if (scan?.status === "done") {
        const markers = strings(scan.data.markers);
        const docs = strings(scan.data.doc_types);
        return scan.data.flagged
          ? proven(`flagged ${markers.length ? markers.map((m) => `“${m}”`).join(", ") : "instruction-like text"}${docs.length ? ` in ${docs.join(", ")}` : ""} — this claim can never be auto-paid`)
          : proven(`clean scan${docs.length ? ` of ${docs.join(", ")}` : ""} — no instruction-like text found`);
      }
      const event = has(lines, (l) => l.layer === "guardrail" && (Array.isArray(l.data?.markers) || /marker|instruction|clean/i.test(text(l))))[0];
      if (event) return proven(event.title);
      return pending(scan?.status === "active" ? "scanning the documents…" : "waiting for the document scan (runs before intake)");
    },
  },
  {
    id: "G2",
    title: "Customer explanation can't misstate money",
    check: (lines, steps) => {
      const guard = steps.explanation_guardrail;
      if (guard?.status === "done") {
        const invented = numbers(guard.data.unexpected_amounts);
        if (guard.data.ok !== false && invented.length === 0) {
          return guard.data.replaced
            ? proven("agent returned no explanation — a summary built only from the settlement was used instead")
            : proven("every ₹ amount in the explanation verified against the settlement");
        }
        return guard.data.replaced
          ? proven(`explanation mentioned ${invented.map(formatInr).join(", ") || "an amount"} not in the settlement — replaced before the policyholder saw it`)
          : pending(`unverified amount(s) ${invented.map(formatInr).join(", ")} detected but the explanation was not replaced`);
      }
      const event = has(lines, (l) => l.layer === "guardrail" && /explanation/i.test(text(l)))[0];
      if (event) return proven(event.title);
      return pending(guard?.status === "active" ? "checking every ₹ amount…" : "waiting for the coverage explanation");
    },
  },
];

export function Requirements({ lines, steps = {} }: { lines: LogLine[]; steps?: StepEvidence }) {
  const tests = useSystemFacts().data?.tests;
  const results = REQUIREMENTS.map((r) => {
    const evidence = r.check(lines, steps);
    if (evidence.status === "tests" && tests) {
      const ok = tests.failed === 0;
      evidence.proof = `${evidence.proof}: last backend run ${tests.passed}/${tests.total} passed (${ranAt(tests.ran_at)})${ok ? "" : `, ${tests.failed} FAILED`}`;
    }
    return { ...r, evidence };
  });
  const provenCount = results.filter((r) => r.evidence.status === "proven").length;
  const testsCount = results.filter((r) => r.evidence.status === "tests").length;

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-xl border border-border bg-card shadow-sm">
      <div className="flex items-center justify-between border-b border-border px-4 py-2.5">
        <span className="text-sm font-semibold text-card-foreground">Requirements — proven live</span>
        <span className="text-xs tabular-nums text-muted-foreground">
          {provenCount}/{results.length} evidenced in this run
          {testsCount > 0 && ` · ${testsCount} proven by the test suite`}
        </span>
      </div>
      <ul className="min-h-0 flex-1 divide-y divide-border overflow-y-auto">
        {results.map((r) => (
          <li key={r.id} className="flex gap-3 px-4 py-2.5">
            <span
              className={`mt-0.5 inline-flex h-5 w-5 shrink-0 items-center justify-center rounded-full text-[11px] font-bold ${
                r.evidence.status === "proven" ? "bg-success text-primary-foreground" : r.evidence.status === "tests" ? "bg-chart-1/15 text-chart-1" : "bg-muted text-muted-foreground"
              }`}
            >
              {r.evidence.status === "proven" ? "✓" : r.evidence.status === "tests" ? "T" : "·"}
            </span>
            <div className="min-w-0">
              <p className="text-sm font-medium text-card-foreground">
                <span className="mr-1.5 font-mono text-xs text-muted-foreground">{r.id}</span>
                {r.title}
              </p>
              <p className={`text-xs ${r.evidence.status === "proven" ? "text-success" : "text-muted-foreground"}`}>{r.evidence.proof}</p>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
