"use client";

import { useSystemFacts } from "@/app/_components/LiveFacts";
import type { ScopeGrant } from "@/lib/api";
import type { LogLine } from "./LiveConsole";

interface StepState {
  status: string;
  summary: string | null;
}

interface AgentDef {
  id: string;
  name: string;
  kind: string;
  /** Workflow steps this agent does its work in (backend step ids). */
  steps: string[];
  role: string;
  /** Shown when the agent needed no data credential in this run. */
  noTokenNote?: string;
  llm: boolean;
}

const AGENTS: AgentDef[] = [
  {
    id: "supervisor",
    name: "claim-assessment",
    kind: "Agno Workflow",
    steps: ["received", "doc_guardrail", "settlement", "explanation_guardrail", "tier"],
    role: "Runs the steps in a fixed order, applies the guardrails and the settlement engine, and routes the claim. Every state change is governed.",
    noTokenNote: "Holds no data access at all: it only hands each agent its input.",
    llm: false,
  },
  {
    id: "intake",
    name: "Intake agent",
    kind: "Agno Agent · LLM",
    steps: ["intake"],
    role: "Reads the bill and discharge summary and extracts line items, dates and totals as typed output.",
    noTokenNote: "The workflow hands it the documents as delimited untrusted text, so it requests no token.",
    llm: true,
  },
  {
    id: "medical_reviewer",
    name: "Medical reviewer",
    kind: "Agno Agent · LLM",
    steps: ["medical"],
    role: "The only agent that sees medical text. Returns an ICD-10 coded finding that every other step uses instead.",
    noTokenNote: "Receives the discharge text from the workflow; nobody else ever gets it.",
    llm: true,
  },
  {
    id: "coverage",
    name: "Coverage agent",
    kind: "Agno Agent · LLM",
    steps: ["coverage"],
    role: "Explains the settlement in plain language. It cannot change a number, and the guardrail checks every ₹ it writes.",
    noTokenNote: "Given the settlement by the workflow; needs no data token.",
    llm: true,
  },
  {
    id: "fraud",
    name: "Fraud agent",
    kind: "Agno Agent · LLM",
    steps: ["fraud"],
    role: "Screens claim history and the hospital watchlist, on pseudonymised data only.",
    llm: true,
  },
  {
    id: "payout",
    name: "Payout agent",
    kind: "Governed tool · own identity",
    steps: ["payout"],
    role: "Moves money only for T2 claims: reads the registered account and records the payment, each with its own 60 s token.",
    noTokenNote: "Not called: the claim went to a human officer, so no money token was ever minted.",
    llm: false,
  },
];

interface AgentStats {
  status: string;
  llmCalls: number;
  tokensUsed: number;
  modelMs: number;
  allowed: number;
  denied: string[];
  credentials: { scope: string; ttl: number | null; jti: string }[];
  refused: string[];
  rows: number;
  gatewayCalls: number;
  summary: string | null;
}

function num(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

function statsFor(agent: AgentDef, lines: LogLine[], steps: Record<string, StepState>, complete: boolean): AgentStats {
  const s: AgentStats = { status: "waiting", llmCalls: 0, tokensUsed: 0, modelMs: 0, allowed: 0, denied: [], credentials: [], refused: [], rows: 0, gatewayCalls: 0, summary: null };
  const states = agent.steps.map((id) => steps[id]?.status).filter(Boolean) as string[];
  if (states.includes("active")) s.status = "working";
  else if (states.includes("blocked")) s.status = "blocked";
  else if (states.length && states.every((st) => st === "done" || st === "skipped")) s.status = states.every((st) => st === "skipped") ? "skipped" : "done";
  else if (states.length) s.status = "done";
  if (complete && s.status === "waiting") s.status = "not used";
  const main = steps[agent.steps[agent.id === "supervisor" ? agent.steps.length - 1 : 0]];
  s.summary = main?.summary ?? null;

  for (const line of lines) {
    const d = line.data ?? {};
    const byAgent = d.agent_id === agent.id;
    if (line.layer === "llm" && line.step && agent.steps.includes(line.step)) {
      s.llmCalls += 1;
      s.tokensUsed += num(d.prompt_tokens) + num(d.completion_tokens);
      s.modelMs += num(d.duration_ms);
    }
    if (!byAgent) continue;
    if (line.layer === "governance") {
      if (line.level === "deny") s.denied.push(String(d.rule_id ?? "denied"));
      else s.allowed += 1;
    } else if (line.layer === "token") {
      if (line.level === "deny") s.refused.push(String(d.rule_id ?? "refused"));
      else if (typeof d.jti === "string") s.credentials.push({ scope: String(d.scope ?? "?"), ttl: typeof d.ttl_s === "number" ? d.ttl_s : null, jti: d.jti });
    } else if (line.layer === "gateway" && line.level !== "deny") {
      s.gatewayCalls += 1;
      s.rows += num(d.rows);
    }
  }
  return s;
}

const STATUS_STYLE: Record<string, string> = {
  waiting: "bg-muted text-muted-foreground",
  working: "bg-chart-1/15 text-chart-1",
  done: "bg-success/15 text-success",
  skipped: "bg-muted text-muted-foreground",
  blocked: "bg-warning/15 text-warning",
  "not used": "bg-muted text-muted-foreground",
};

/** The agents behind the claim, as they work: what each one is for, the
 * AI calls it made, the governed decisions about it, and every short-lived
 * credential it was issued (scope, lifetime, jti). All figures come from
 * the backend's live events for this run, never from a script. */
export function AgentsPanel({ lines, steps, running, complete }: { lines: LogLine[]; steps: Record<string, StepState>; running: boolean; complete: boolean }) {
  // Each agent's allowed scopes, read live from the token service's matrix.
  const matrix = useSystemFacts().data?.scope_matrix;
  return (
    <section className="rounded-xl border border-border bg-card shadow-sm p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <div>
          <h2 className="font-semibold text-card-foreground">Agents at work</h2>
          <p className="text-xs text-muted-foreground">
            Each agent has its own Ed25519 identity. When it needs data it gets its own short-lived JWT for one collection, and every
            action is checked by AGT policy first.
          </p>
        </div>
        {running && (
          <span className="flex items-center gap-1.5 text-xs text-chart-1">
            <span className="h-2 w-2 animate-pulse rounded-full bg-chart-1" /> live
          </span>
        )}
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {AGENTS.map((agent) => (
          <AgentCard key={agent.id} agent={agent} stats={statsFor(agent, lines, steps, complete)} scopes={matrix?.[agent.id]} />
        ))}
      </div>
    </section>
  );
}

function AgentCard({ agent, stats, scopes }: { agent: AgentDef; stats: AgentStats; scopes?: ScopeGrant[] }) {
  const finished = ["done", "skipped", "blocked", "not used"].includes(stats.status);
  return (
    <div className={`flex flex-col rounded-md border p-3 transition-colors ${stats.status === "working" ? "border-chart-1/60 bg-chart-1/5" : "border-border"}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-card-foreground">{agent.name}</p>
          <p className="text-[11px] text-muted-foreground">
            {agent.kind} · <span className="font-mono">{agent.id}</span>
          </p>
        </div>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${STATUS_STYLE[stats.status] ?? STATUS_STYLE.waiting}`}>
          {stats.status === "working" ? "working…" : stats.status}
        </span>
      </div>
      <p className="mt-2 text-xs text-muted-foreground">{agent.role}</p>

      <div className="mt-2 grid grid-cols-3 gap-1.5 text-center">
        <Mini label="AI calls" value={agent.llm ? String(stats.llmCalls) : "—"} sub={agent.llm && stats.tokensUsed ? `${stats.tokensUsed.toLocaleString("en-IN")} tok` : agent.llm ? "" : "no LLM"} />
        <Mini label="Policy checks" value={String(stats.allowed + stats.denied.length)} sub={stats.denied.length ? `${stats.denied.length} denied` : stats.allowed ? "all allowed" : ""} warn={stats.denied.length > 0} />
        <Mini label="JWTs issued" value={String(stats.credentials.length)} sub={stats.gatewayCalls ? `${stats.gatewayCalls} gateway call(s)` : ""} />
      </div>

      {(stats.credentials.length > 0 || stats.refused.length > 0 || stats.denied.length > 0) && (
        <ul className="mt-2 flex flex-col gap-1">
          {stats.credentials.map((c) => (
            <li key={c.jti} className="flex flex-wrap items-center gap-1.5 rounded bg-secondary px-2 py-1 font-mono text-[11px]">
              <span className="font-semibold text-chart-3">{c.scope}</span>
              {c.ttl != null && <span className="text-muted-foreground">ttl {c.ttl}s</span>}
              <span className="text-muted-foreground">jti {c.jti.slice(0, 8)}…</span>
            </li>
          ))}
          {stats.refused.map((r, i) => (
            <li key={`r${i}`} className="rounded bg-destructive/10 px-2 py-1 font-mono text-[11px] text-destructive">token refused · {r}</li>
          ))}
          {stats.denied.map((r, i) => (
            <li key={`d${i}`} className="rounded bg-destructive/10 px-2 py-1 font-mono text-[11px] text-destructive">policy denied · {r}</li>
          ))}
        </ul>
      )}
      {finished && stats.credentials.length === 0 && agent.noTokenNote && <p className="mt-2 text-[11px] italic text-muted-foreground">{agent.noTokenNote}</p>}

      {stats.summary && finished && (
        <p className="mt-2 rounded bg-secondary/60 px-2 py-1 text-xs text-card-foreground">
          <span className="font-medium">Result: </span>
          {stats.summary}
        </p>
      )}

      {scopes && scopes.length > 0 && (
        <div className="mt-auto flex flex-wrap gap-1 pt-2">
          {scopes.map((g) => (
            <span key={g.scope} className="rounded border border-border px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground" title={`Allowed by the token service's matrix · minimum trust ${g.min_trust}`}>
              {g.scope} · {g.ttl_s}s
            </span>
          ))}
        </div>
      )}
    </div>
  );
}

function Mini({ label, value, sub, warn }: { label: string; value: string; sub?: string; warn?: boolean }) {
  return (
    <div className="rounded bg-secondary px-1.5 py-1">
      <p className={`text-sm font-semibold tabular-nums ${warn ? "text-destructive" : "text-card-foreground"}`}>{value}</p>
      <p className="text-[10px] uppercase tracking-wide text-muted-foreground">{label}</p>
      {sub && <p className="truncate text-[10px] text-muted-foreground">{sub}</p>}
    </div>
  );
}
