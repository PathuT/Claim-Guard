"use client";

import type { LogLine } from "./LiveConsole";

/** The system's request path as a live diagram: each node is one real
 * component, lit (with an operation count) when the backend actually uses
 * it in this run, and pulsing while it is the component currently working. */
interface Node {
  id: string;
  name: string;
  tech: string;
  role: string;
  layers: string[];
}

const MAIN_PATH: Node[] = [
  { id: "console", name: "Console", tech: "Next.js · TypeScript", role: "Upload, live run, officer & compliance views", layers: ["console"] },
  { id: "api", name: "Agno AgentOS", tech: "FastAPI · pypdf", role: "Receives the claim, extracts PDF text, streams events", layers: ["api", "document"] },
  { id: "agents", name: "Agno Workflow + 4 agents", tech: "Agno · Groq LLM", role: "Intake → medical → coverage → fraud, then the payout branch", layers: ["agent", "llm"] },
  { id: "rules", name: "Deterministic rules", tech: "Python", role: "Settlement maths, tiers T0–T3", layers: ["rules"] },
  { id: "governance", name: "Governance adapter", tech: "Microsoft AGT", role: "Allow / deny every tool call, state machine", layers: ["governance", "state"] },
  { id: "token", name: "Token service", tech: "Ed25519 · PyJWT EdDSA", role: "Verifies agent identity, mints ≤300 s scoped JWT", layers: ["identity", "token"] },
  { id: "gateway", name: "Data gateway", tech: "FastAPI · SQLAlchemy", role: "Validates token, row binding, field allowlist", layers: ["gateway", "payment"] },
  { id: "db", name: "Database", tech: "Postgres 16 · pgvector · Supabase", role: "Policies, claims, bank details, payments", layers: ["database"] },
];

const SIDE: Node[] = [
  { id: "audit", name: "Audit trail", tech: "AGT FlightRecorder", role: "Append-only, hash-chained", layers: ["audit"] },
  { id: "trace", name: "Tracing", tech: "OpenTelemetry → Arize Phoenix", role: "One redacted trace per claim", layers: ["trace"] },
  { id: "evals", name: "Evaluations", tech: "Harbor", role: "S01–S10 re-run as automated tests", layers: [] },
];

function stats(lines: LogLine[]) {
  const counts: Record<string, number> = {};
  for (const line of lines) counts[line.layer] = (counts[line.layer] ?? 0) + 1;
  const last = lines.length > 0 ? lines[lines.length - 1].layer : null;
  return { counts, last };
}

function NodeBox({ node, count, current }: { node: Node; count: number; current: boolean }) {
  const lit = count > 0;
  return (
    <div
      className={`relative rounded-md border px-3 py-2 transition-all duration-300 ${
        current ? "border-chart-1 bg-chart-1/10 shadow-md ring-2 ring-chart-1/30" : lit ? "border-success/40 bg-success/5" : "border-border bg-secondary opacity-70"
      }`}
    >
      <div className="flex items-center justify-between gap-2">
        <span className="text-sm font-semibold text-card-foreground">{node.name}</span>
        {lit && <span className="rounded-full bg-card px-1.5 text-[10px] font-medium tabular-nums text-muted-foreground">{count}</span>}
      </div>
      <p className="font-mono text-[11px] text-chart-1">{node.tech}</p>
      <p className="text-[11px] text-muted-foreground">{node.role}</p>
      {current && <span className="absolute -right-1 -top-1 h-2.5 w-2.5 animate-ping rounded-full bg-chart-1" />}
    </div>
  );
}

export function SystemFlow({ lines, live }: { lines: LogLine[]; live: boolean }) {
  const { counts, last } = stats(lines);
  const countFor = (node: Node) => (node.id === "console" ? Math.max(1, counts.console ?? 0) : node.layers.reduce((n, l) => n + (counts[l] ?? 0), 0));
  const isCurrent = (node: Node) => live && last != null && node.layers.includes(last);

  return (
    <section className="rounded-lg border border-border bg-card p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="font-semibold text-card-foreground">System flow {live ? "— live" : ""}</h2>
        <span className="text-xs text-muted-foreground">A request can only move along this path: no governance approval, no token; no token, no data.</span>
      </div>
      <div className="mt-4 grid gap-4 lg:grid-cols-[minmax(0,3fr)_minmax(0,1fr)]">
        <ol className="grid grid-cols-1 gap-2 sm:grid-cols-2 xl:grid-cols-4">
          {MAIN_PATH.map((node, i) => (
            <li key={node.id} className="relative">
              <span className="absolute -left-1 -top-2 z-10 rounded bg-card px-1 font-mono text-[10px] text-muted-foreground">{i + 1}</span>
              <NodeBox node={node} count={countFor(node)} current={isCurrent(node)} />
            </li>
          ))}
        </ol>
        <div className="flex flex-col gap-2 border-t border-dashed border-border pt-3 lg:border-l lg:border-t-0 lg:pl-4 lg:pt-0">
          <span className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">Across every step</span>
          {SIDE.map((node) => (
            <NodeBox key={node.id} node={node} count={countFor(node)} current={isCurrent(node)} />
          ))}
        </div>
      </div>
    </section>
  );
}
