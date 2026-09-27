"use client";

import { useEffect, useRef, useState } from "react";
import { LAYER_LABEL, LAYER_TECH, TECH } from "@/lib/liveRun";

export interface LogLine {
  id: number;
  t: number;
  kind: "log" | "trace";
  layer: string;
  level: string;
  title: string;
  detail: string | null;
  /** The workflow step that was running when the event happened (intake,
   * medical, coverage, fraud, payout, ...), stamped by the backend. */
  step?: string | null;
  /** The event's structured payload, kept so the run meter can sum it
   * (LLM token counts and durations, governance rule ids, token jtis). */
  data: Record<string, unknown>;
}

const LAYER_COLOR: Record<string, string> = {
  api: "#7aa2f7",
  document: "#e0af68",
  agent: "#bb9af7",
  llm: "#f7768e",
  rules: "#9ece6a",
  guardrail: "#1abc9c",
  governance: "#ff9e64",
  identity: "#2ac3de",
  token: "#2ac3de",
  gateway: "#73daca",
  database: "#7dcfff",
  audit: "#c0caf5",
  evals: "#e0af68",
  state: "#ff9e64",
  payment: "#9ece6a",
  trace: "#565f89",
  console: "#a9b1d6",
};

const LEVEL_COLOR: Record<string, string> = {
  success: "#9ece6a",
  warn: "#e0af68",
  deny: "#f7768e",
  error: "#f7768e",
};

const LEVEL_MARK: Record<string, string> = {
  success: "✓",
  warn: "!",
  deny: "✗",
  error: "✗",
};

function formatT(ms: number): string {
  return `+${(ms / 1000).toFixed(2).padStart(6, " ")}s`;
}

/** The live backend log: every operation the backend performs for this
 * claim, streamed as it happens, tagged with its architectural layer. */
export function LiveConsole({ lines, running }: { lines: LogLine[]; running: boolean }) {
  const [showSpans, setShowSpans] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const visible = showSpans ? lines : lines.filter((l) => l.kind === "log");
  const spanCount = lines.length - lines.filter((l) => l.kind === "log").length;

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [visible.length]);

  return (
    <div className="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-[#24283b] bg-[#11131c] text-[#c0caf5] shadow-sm">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b border-[#24283b] px-4 py-2.5">
        <div className="flex items-center gap-2">
          <span className={`h-2 w-2 rounded-full ${running ? "animate-pulse bg-[#9ece6a]" : "bg-[#565f89]"}`} />
          <span className="font-mono text-xs font-semibold tracking-wide">BACKEND · LIVE</span>
          <span className="font-mono text-[11px] text-[#565f89]">{lines.filter((l) => l.kind === "log").length} operations</span>
        </div>
        <label className="flex cursor-pointer items-center gap-1.5 font-mono text-[11px] text-[#a9b1d6]">
          <input type="checkbox" checked={showSpans} onChange={(e) => setShowSpans(e.target.checked)} className="accent-[#7aa2f7]" />
          show OpenTelemetry spans ({spanCount})
        </label>
      </div>
      <div ref={scrollRef} className="min-h-0 flex-1 overflow-y-auto px-3 py-2 font-mono text-[12px] leading-relaxed">
        {visible.length === 0 && (
          <p className="px-1 py-6 text-center text-[#565f89]">Waiting for the first backend operation…</p>
        )}
        {visible.map((line) => (
          <div key={line.id} className="grid grid-cols-[4.5rem_5.5rem_1fr] gap-x-2 border-b border-[#1a1d2b] py-1 last:border-b-0">
            <span className="whitespace-pre text-[#565f89]">{formatT(line.t)}</span>
            <span className="truncate font-semibold" style={{ color: LAYER_COLOR[line.layer] ?? "#a9b1d6" }}>
              {LAYER_LABEL[line.layer] ?? line.layer.toUpperCase()}
            </span>
            <span className="min-w-0">
              <span style={{ color: LEVEL_COLOR[line.level] ?? "#c0caf5" }}>
                {LEVEL_MARK[line.level] ? `${LEVEL_MARK[line.level]} ` : ""}
                {line.title}
              </span>
              {line.detail && <span className="block break-words text-[11px] text-[#737aa2]">{line.detail}</span>}
            </span>
          </div>
        ))}
        {running && <div className="px-1 py-1 text-[#565f89]">▍</div>}
      </div>
    </div>
  );
}

export interface RunMeterStats {
  llmCalls: number;
  /** LLM calls whose span reported no token counts (provider-dependent). */
  callsWithoutTokens: number;
  promptTokens: number;
  completionTokens: number;
  modelMs: number;
  models: string[];
  allow: number;
  deny: number;
  deniedRules: string[];
  minted: number;
  tokenRefusals: string[];
}

const finite = (v: unknown): number | null => (typeof v === "number" && Number.isFinite(v) ? v : null);

/** Sums what this run actually spent, straight from the streamed events:
 * LLM spans (layer "llm", data {model, duration_ms, prompt_tokens,
 * completion_tokens}), AGT policy decisions (layer "governance") and token
 * issuance (layer "token"). Nothing is estimated. */
export function runMeterStats(lines: LogLine[]): RunMeterStats {
  const s: RunMeterStats = {
    llmCalls: 0,
    callsWithoutTokens: 0,
    promptTokens: 0,
    completionTokens: 0,
    modelMs: 0,
    models: [],
    allow: 0,
    deny: 0,
    deniedRules: [],
    minted: 0,
    tokenRefusals: [],
  };
  for (const line of lines) {
    const data = line.data ?? {};
    if (line.layer === "llm") {
      s.llmCalls += 1;
      const prompt = finite(data.prompt_tokens);
      const completion = finite(data.completion_tokens);
      if (prompt == null && completion == null) s.callsWithoutTokens += 1;
      s.promptTokens += prompt ?? 0;
      s.completionTokens += completion ?? 0;
      s.modelMs += finite(data.duration_ms) ?? 0;
      if (typeof data.model === "string" && !s.models.includes(data.model)) s.models.push(data.model);
    } else if (line.layer === "governance" && (typeof data.audit_id === "string" || /policy check (ALLOW|DENY)/.test(line.title))) {
      // One entry per AGT decision (each is also a FlightRecorder audit
      // entry). The supervisor's "Payout refused … falling back" line is a
      // consequence of a deny already counted here, so it is not matched.
      if (line.level === "deny") {
        s.deny += 1;
        const rule = typeof data.rule_id === "string" ? data.rule_id : line.title.split("— ")[1];
        if (rule && !s.deniedRules.includes(rule)) s.deniedRules.push(rule);
      } else {
        s.allow += 1;
      }
    } else if (line.layer === "token") {
      if (/minted/.test(line.title)) s.minted += 1;
      else if (line.level === "deny") s.tokenRefusals.push(line.title.split("— ")[1] ?? "refused");
    }
  }
  return s;
}

function fmtCount(n: number): string {
  return n.toLocaleString("en-IN");
}

function fmtSeconds(ms: number): string {
  return `${(ms / 1000).toFixed(ms < 10_000 ? 1 : 0)} s`;
}

function MeterTile({ label, value, children }: { label: string; value: string; children?: React.ReactNode }) {
  return (
    <div className="flex min-w-0 flex-col gap-0.5 rounded-md bg-secondary px-3 py-2">
      <span className="text-[11px] text-muted-foreground">{label}</span>
      <span className="text-lg font-semibold leading-tight text-card-foreground">{value}</span>
      {children && <div className="text-[11px] text-muted-foreground">{children}</div>}
    </div>
  );
}

/** The "Now playing" cost & token meter: model usage, time in the model vs
 * end to end, governance decisions and scoped credentials — measured from
 * this run's events. Token counts only; no prices are invented. */
export function RunMeter({
  lines,
  elapsedMs,
  running,
  runStarted,
}: {
  lines: LogLine[];
  /** Server-measured end-to-end time of the claim run, once it finished. */
  elapsedMs: number | null;
  running: boolean;
  /** True once the claim assessment itself has started (not just the upload). */
  runStarted: boolean;
}) {
  const s = runMeterStats(lines);
  const totalTokens = s.promptTokens + s.completionTokens;
  // Until the result arrives, compare against the time elapsed so far.
  const wallMs = elapsedMs ?? (running && lines.length > 0 ? lines[lines.length - 1].t : null);
  const share = wallMs && wallMs > 0 ? Math.min(1, s.modelMs / wallMs) : null;

  return (
    <div className="flex flex-col gap-2">
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3 xl:grid-cols-5">
        <MeterTile label="LLM calls" value={fmtCount(s.llmCalls)}>
          <span className="block truncate" title={s.models.join(", ")}>
            {s.models.length > 0 ? s.models.join(", ") : s.llmCalls === 0 ? "none yet" : "model not reported"}
          </span>
        </MeterTile>
        <MeterTile label="Model tokens" value={fmtCount(totalTokens)}>
          {fmtCount(s.promptTokens)} prompt + {fmtCount(s.completionTokens)} completion
        </MeterTile>
        <MeterTile label="Time in the model" value={fmtSeconds(s.modelMs)}>
          {share != null && wallMs != null ? (
            <>
              <span
                className="mt-1 block h-1.5 overflow-hidden rounded-full bg-chart-1/15"
                role="meter"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(share * 100)}
                aria-label="Share of end-to-end time spent in the model"
              >
                <span className="block h-full rounded-full bg-chart-1 transition-all duration-500" style={{ width: `${share * 100}%` }} />
              </span>
              <span className="mt-1 block">
                {Math.round(share * 100)}% of {fmtSeconds(wallMs)} {elapsedMs != null ? "end-to-end" : "so far"}
              </span>
            </>
          ) : (
            "sum of every LLM call's latency"
          )}
        </MeterTile>
        <MeterTile label="Governance decisions" value={fmtCount(s.allow + s.deny)}>
          {fmtCount(s.allow)} allow ·{" "}
          <span className={s.deny > 0 ? "font-medium text-destructive" : undefined}>
            {fmtCount(s.deny)} deny{s.deniedRules.length > 0 ? ` (${s.deniedRules.join(", ")})` : ""}
          </span>
        </MeterTile>
        <MeterTile label="Scoped tokens minted" value={fmtCount(s.minted)}>
          {s.tokenRefusals.length > 0 ? (
            <span className="font-medium text-destructive">
              {s.tokenRefusals.length} refused ({s.tokenRefusals.join(", ")})
            </span>
          ) : (
            "one agent, one scope, ≤ 300 s each"
          )}
        </MeterTile>
      </div>
      <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 text-[11px] text-muted-foreground">
        {runStarted && (
          <span>
            <span className="font-medium text-card-foreground">Orchestration tokens: 0</span> — the Agno Workflow&apos;s order and payout branch are code
          </span>
        )}
        <span>
          Counted from this run&apos;s live events; token counts as reported by the model provider
          {s.callsWithoutTokens > 0 ? ` (${s.callsWithoutTokens} call(s) reported none)` : ""}. No prices estimated.
        </span>
      </div>
    </div>
  );
}

/** The project's technology stack, each lighting up (with a count) the
 * moment the backend actually uses it in this run. */
export function TechStrip({ lines }: { lines: LogLine[] }) {
  const counts: Record<string, number> = { nextjs: 1 };
  for (const line of lines) {
    const tech = LAYER_TECH[line.layer];
    if (tech) counts[tech] = (counts[tech] ?? 0) + 1;
  }
  return (
    <div className="flex flex-wrap gap-1.5">
      {TECH.map((tech) => {
        const n = counts[tech.id] ?? 0;
        return (
          <span
            key={tech.id}
            title={tech.role}
            className={`inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-all duration-500 ${
              n > 0 ? "border-primary/40 bg-primary/10 text-foreground" : "border-border bg-card text-muted-foreground opacity-60"
            }`}
          >
            <span className={`h-1.5 w-1.5 rounded-full ${n > 0 ? "bg-success" : "bg-border"}`} />
            {tech.name}
            {n > 0 && tech.id !== "nextjs" && <span className="tabular-nums text-muted-foreground">{n}</span>}
          </span>
        );
      })}
    </div>
  );
}
