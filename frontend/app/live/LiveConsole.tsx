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
}

const LAYER_COLOR: Record<string, string> = {
  api: "#7aa2f7",
  document: "#e0af68",
  agent: "#bb9af7",
  llm: "#f7768e",
  rules: "#9ece6a",
  governance: "#ff9e64",
  identity: "#2ac3de",
  token: "#2ac3de",
  gateway: "#73daca",
  database: "#7dcfff",
  audit: "#c0caf5",
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
