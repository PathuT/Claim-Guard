"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import {
  ApiError,
  type AuditEntry,
  type ClaimEvaluation,
  type LiveEvent,
  type NewClaimFields,
  type SamplePack,
  fetchSampleFile,
  getClaimAudit,
  getClaimEvaluation,
  listSamplePacks,
  startClaimEvaluation,
  streamAttack,
  streamClaimRun,
  submitNewClaim,
} from "@/lib/api";
import { formatInr, humanizeStatus, severityStyle, statusStyle } from "@/lib/format";
import { ATTACK_STEPS, CHAPTERS, type Chapter, MILESTONES, RULE_TEXT, TECH } from "@/lib/liveRun";
import { AgentsPanel } from "./AgentsPanel";
import { ClaimEvaluationCard } from "./ClaimEvaluationCard";
import { EvalsPanel } from "./EvalsPanel";
import { LiveConsole, type LogLine, RunMeter, TechStrip } from "./LiveConsole";
import { StartPanel } from "./StartPanel";
import { Requirements } from "./Requirements";
import { SystemFlow } from "./SystemFlow";

interface StepState {
  status: string;
  summary: string | null;
  data: Record<string, unknown>;
}

interface RunResult {
  claim_id: string;
  tier: string | null;
  final_state: string;
  payable_amount: number | null;
  explanation: string | null;
  fraud_flags: { type: string; severity: string; evidence_ref: string }[] | null;
}

interface AttackResult {
  all_blocked: boolean;
  attempts: { attempt: string; denied: boolean; rule_id: string | null; message: string }[];
}

type Phase = "idle" | "uploading" | "running" | "done" | "attacking" | "attacked";

export default function LiveRunPage() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [title, setTitle] = useState<string | null>(null);
  const [claimId, setClaimId] = useState<string | null>(null);
  const [traceId, setTraceId] = useState<string | null>(null);
  const [lines, setLines] = useState<LogLine[]>([]);
  const [steps, setSteps] = useState<Record<string, StepState>>({});
  const [result, setResult] = useState<RunResult | null>(null);
  const [elapsedMs, setElapsedMs] = useState<number | null>(null);
  const [audit, setAudit] = useState<AuditEntry[] | null>(null);
  const [attack, setAttack] = useState<AttackResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [poisoned, setPoisoned] = useState(false);
  const [panel, setPanel] = useState<"log" | "requirements">("log");
  const [evaluation, setEvaluation] = useState<ClaimEvaluation | null>(null);
  const [evaluating, setEvaluating] = useState(false);

  const startedAt = useRef(0);
  const nextId = useRef(0);
  // Which sample pack (if any) the current claim came from, so Harbor knows
  // the expected outcome; and a run counter so a new run stops old polling.
  const packId = useRef<string | null>(null);
  const runToken = useRef(0);

  const busy = phase === "uploading" || phase === "running" || phase === "attacking";

  function reset(runTitle: string) {
    startedAt.current = performance.now();
    nextId.current = 0;
    setTitle(runTitle);
    setClaimId(null);
    setTraceId(null);
    setLines([]);
    setSteps({});
    setResult(null);
    setElapsedMs(null);
    setAudit(null);
    setAttack(null);
    setError(null);
    setEvaluation(null);
    setEvaluating(false);
    packId.current = null;
    runToken.current += 1;
  }

  function log(
    layer: string,
    title: string,
    detail: string | null = null,
    level = "info",
    kind: "log" | "trace" = "log",
    data: Record<string, unknown> = {},
    step: string | null = null,
  ) {
    const line: LogLine = { id: nextId.current++, t: performance.now() - startedAt.current, kind, layer, level, title, detail, data, step };
    setLines((prev) => [...prev, line]);
  }

  function setStep(step: string, status: string, summary: string | null = null, data: Record<string, unknown> = {}) {
    setSteps((prev) => ({ ...prev, [step]: { status, summary, data } }));
  }

  function handleEvent(event: LiveEvent, onResult?: (result: Record<string, unknown>) => void) {
    switch (event.kind) {
      case "start":
        setTraceId(event.trace_id);
        break;
      case "log":
      case "trace":
        log(event.layer, event.title, event.detail, event.level, event.kind, event.data ?? {}, event.step ?? null);
        break;
      case "step":
        setStep(event.step, event.status, event.summary, event.data);
        break;
      case "result":
        setTraceId(event.trace_id);
        // Keep the claim run's end-to-end time: the red-team replay that may
        // follow has its own (much shorter) result and must not replace it.
        setElapsedMs((prev) => prev ?? event.elapsed_ms);
        onResult?.(event.result);
        break;
      case "error":
        setError(event.reason_code ? `${event.message} (${event.reason_code})` : event.message);
        log("api", "Run failed", event.message, "error");
        break;
      case "end":
        break;
    }
  }

  async function runLive(id: string) {
    setClaimId(id);
    setPhase("running");
    log("console", `POST /claims/${id}/live — streaming the assessment`, "Next.js → AgentOS (FastAPI) · text/event-stream");
    let assessed = false;
    try {
      await streamClaimRun(id, (event) =>
        handleEvent(event, (r) => {
          assessed = true;
          setResult(r as unknown as RunResult);
          log("console", "Assessment complete", `final state: ${String(r.final_state)}`, "success");
        }),
      );
      try {
        const trail = await getClaimAudit(id);
        setAudit(trail.entries);
      } catch {
        setAudit([]);
      }
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The live stream failed.");
    }
    setPhase("done");
    if (assessed) void evaluateClaim(id);
  }

  /** After every claim: Harbor checks this one claim (outcome + governance
   * evidence) with the same verifier as S01–S10, then the card shows why. */
  async function evaluateClaim(id: string) {
    const token = runToken.current;
    setEvaluating(true);
    log("evals", "Harbor: checking this claim", "one-task Harbor job · same verifier as S01–S10 · read-only, no AI calls");
    try {
      let current = await startClaimEvaluation(id, packId.current);
      const deadline = Date.now() + 5 * 60_000;
      while (current.status === "running" && Date.now() < deadline) {
        if (token !== runToken.current) return;
        setEvaluation(current);
        await new Promise((resolve) => setTimeout(resolve, 2000));
        current = await getClaimEvaluation(id);
      }
      if (token !== runToken.current) return;
      setEvaluation(current);
      if (current.status === "done") {
        const passed = current.outcome === 1 && current.governance === 1;
        const failed = current.checks.filter((c) => !c.passed).map((c) => c.label);
        log(
          "evals",
          passed ? "Harbor: outcome ✓ governance ✓ — claim verified" : `Harbor: ${failed.length} check(s) failed`,
          passed ? `${current.checks.length} checks passed · ${current.expectation_source}` : failed.join(" · "),
          passed ? "success" : "error",
        );
      } else {
        log("evals", "Harbor check did not complete", current.error ?? `status ${current.status}`, "warn");
      }
    } catch (err) {
      if (token !== runToken.current) return;
      // A bare 404 here means AgentOS is still running code from before the
      // per-claim Harbor endpoint existed; say so instead of "Not Found".
      const message =
        err instanceof ApiError && err.status === 404 && !err.reasonCode
          ? "AgentOS is running an older build without the Harbor check endpoint. Restart `npm run dev` and run the claim again."
          : err instanceof ApiError
            ? err.message
            : "request failed";
      log("evals", "Harbor check could not start", message, "warn");
      setEvaluation({ claim_id: id, status: "error", job: null, expectation_source: null, started_at: null, duration_s: null, outcome: null, governance: null, checks: [], error: message });
    } finally {
      if (token === runToken.current) setEvaluating(false);
    }
  }

  async function runUpload(fields: NewClaimFields, runTitle: string) {
    setPhase("uploading");
    setStep("upload", "active");
    log("console", "POST /claims/new — uploading 2 PDF files", "multipart/form-data · the real upload endpoint, not a replay");
    try {
      const created = await submitNewClaim(fields);
      for (const doc of created.documents) {
        log(
          "document",
          `${doc.doc_type}: ${doc.pages} page(s), ${doc.extracted_chars.toLocaleString("en-IN")} characters extracted`,
          `${(doc.size_bytes / 1024).toFixed(1)} KB · sha256 ${doc.sha256.slice(0, 16)}… · stored as untrusted input`,
          "success",
        );
        if (doc.injection_markers.length > 0) {
          log(
            "document",
            `Hidden instruction-like text inside ${doc.doc_type}`,
            `markers: ${doc.injection_markers.join(", ")} — invisible on the page, present in the text layer`,
            "warn",
          );
        }
      }
      log("database", `Claim ${created.claim_id} created in Postgres`, "status=submitted · documents + hashes recorded", "success");
      setStep("upload", "done", `${created.documents.length} documents read`, { documents: created.documents });
      setTitle(`${runTitle} · ${created.claim_id}`);
      await runLive(created.claim_id);
    } catch (err) {
      setStep("upload", "blocked", "Upload rejected");
      setError(err instanceof ApiError ? `${err.message}${err.reasonCode ? ` (${err.reasonCode})` : ""}` : "Upload failed.");
      setPhase("done");
    }
  }

  async function handleSamplePack(pack: SamplePack) {
    reset(pack.title);
    packId.current = pack.pack_id;
    setPoisoned(pack.poisoned);
    setPhase("uploading");
    log("console", "Fetching the sample PDFs", "real files rendered by the synthetic-data generator (reportlab)");
    try {
      // Re-read the pack so its dates match the PDFs rendered right now
      // (each pack moves to a fresh, non-overlapping date window once used).
      pack = (await listSamplePacks()).find((p) => p.pack_id === pack.pack_id) ?? pack;
      const [finalBill, dischargeSummary] = await Promise.all([
        fetchSampleFile(pack.pack_id, "final_bill"),
        fetchSampleFile(pack.pack_id, "discharge_summary"),
      ]);
      await runUpload(
        {
          policyNumber: pack.policy_number,
          memberId: pack.member_id,
          hospitalId: pack.hospital_id,
          admissionDate: pack.admission_date,
          dischargeDate: pack.discharge_date,
          statedIllness: pack.stated_illness,
          claimedAmount: pack.claimed_amount,
          finalBill,
          dischargeSummary,
        },
        pack.title,
      );
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "Could not load the sample documents.");
      setPhase("done");
    }
  }

  function handleUpload(fields: NewClaimFields) {
    reset("Your uploaded claim");
    setPoisoned(false);
    void runUpload(fields, "Your uploaded claim");
  }

  function handleReplay(id: string, label: string) {
    reset(`${label} · ${id}`);
    setPoisoned(id === "CLM-2026-018839");
    void runLive(id);
  }

  async function handleAttack() {
    if (!claimId) return;
    setPhase("attacking");
    log("console", `POST /claims/${claimId}/live/attack — red-team replay`, "simulating an agent that obeyed the hidden instruction");
    try {
      await streamAttack(claimId, (event) =>
        handleEvent(event, (r) => {
          setAttack(r as unknown as AttackResult);
          log("console", (r as unknown as AttackResult).all_blocked ? "Every attack was blocked" : "An attack was NOT blocked", null, (r as unknown as AttackResult).all_blocked ? "success" : "error");
        }),
      );
      const trail = await getClaimAudit(claimId);
      setAudit(trail.entries);
    } catch (err) {
      setError(err instanceof ApiError ? err.message : "The red-team stream failed.");
    }
    setPhase("attacked");
  }

  const started = phase !== "idle";
  const payoutRefusedBy = payoutRefusal(lines);
  const replacedExplanation = guardrailExplanation(lines);

  return (
    <div className="flex flex-col gap-6">
      <Intro />

      <StartPanel disabled={busy} onSamplePack={handleSamplePack} onUpload={handleUpload} onReplay={handleReplay} />

      {started && (
        <>
          <section className="flex flex-col gap-3 rounded-xl border border-border bg-card shadow-sm p-4">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <div className="flex flex-col">
                <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Now playing</span>
                <span className="font-semibold text-card-foreground">{title}</span>
              </div>
              <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                {traceId && (
                  <span className="font-mono" title="Search this id in Phoenix to open the full trace">
                    trace {traceId.slice(0, 16)}…
                  </span>
                )}
                {elapsedMs != null && <span className="tabular-nums">{(elapsedMs / 1000).toFixed(1)} s end-to-end</span>}
                <span className={`rounded-full px-2 py-0.5 font-medium ${busy ? "bg-chart-1/10 text-chart-1" : "bg-muted text-muted-foreground"}`}>
                  {phase === "uploading" ? "uploading" : phase === "running" ? "agents working" : phase === "attacking" ? "red-team running" : "finished"}
                </span>
              </div>
            </div>
            <RunMeter lines={lines} elapsedMs={elapsedMs} running={busy} runStarted={claimId != null} />
            <TechStrip lines={lines} />
          </section>

          <SystemFlow lines={lines} live={busy} />

          <AgentsPanel lines={lines} steps={steps} running={phase === "running"} complete={result != null || (phase !== "running" && phase !== "uploading")} />

          {error && <p className="rounded-md border border-destructive/40 bg-destructive/10 p-3 text-sm text-destructive">{error}</p>}

          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_minmax(0,1.05fr)]">
            <div className="flex flex-col gap-3">
              {CHAPTERS.map((chapter, i) => (
                <ChapterCard
                  key={chapter.id}
                  index={i + 1}
                  chapter={chapter}
                  status={chapterStatus(chapter, steps, result, phase)}
                  steps={steps}
                  result={result}
                  audit={audit}
                  traceId={traceId}
                  payoutRefusedBy={payoutRefusedBy}
                  replacedExplanation={replacedExplanation}
                />
              ))}
              {result && <Outcome result={result} claimId={claimId} payoutRefusedBy={payoutRefusedBy} />}
              {result && (evaluating || evaluation) && <ClaimEvaluationCard evaluation={evaluation} starting={evaluating && !evaluation} />}
              {result && (
                <AttackChapter
                  poisoned={poisoned}
                  phase={phase}
                  steps={steps}
                  attack={attack}
                  onRun={handleAttack}
                />
              )}
            </div>
            <div className="lg:sticky lg:top-4 lg:h-[calc(100vh-2rem)] lg:self-start">
              <div className="flex h-[36rem] flex-col gap-2 lg:h-full">
                <div className="flex gap-1 rounded-md bg-secondary p-1">
                  {(["log", "requirements"] as const).map((id) => (
                    <button
                      key={id}
                      type="button"
                      onClick={() => setPanel(id)}
                      className={`flex-1 rounded px-3 py-1.5 text-xs font-medium transition-colors ${
                        panel === id ? "bg-card text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"
                      }`}
                    >
                      {id === "log" ? "Backend log (live)" : "Requirements proof"}
                    </button>
                  ))}
                </div>
                <div className="min-h-0 flex-1">
                  {panel === "log" ? <LiveConsole lines={lines} running={busy} /> : <Requirements lines={lines} steps={steps} />}
                </div>
              </div>
            </div>
          </div>
        </>
      )}

      {!started && <SystemFlow lines={[]} live={false} />}
      <EvalsPanel />
      <BuildJourney />
    </div>
  );
}

/** The rule that refused the automatic (T2) payout, if governance did —
 * the supervisor then falls back to a human officer. Its detail line is
 * "<RULE-ID>: <reason>". */
function payoutRefusal(lines: LogLine[]): string | null {
  const line = lines.find((l) => l.layer === "governance" && l.level === "deny" && /Payout refused by governance/.test(l.title));
  if (!line) return null;
  const id = line.detail?.split(":")[0]?.trim() ?? "";
  return /^[A-Z][A-Z0-9-]+$/.test(id) ? id : "unspecified rule";
}

/** The explanation the guardrail put in place of the agent's draft, carried
 * on its "guardrail" log event (the explanation_guardrail step itself only
 * reports ok / unexpected_amounts / replaced). */
function guardrailExplanation(lines: LogLine[]): string | null {
  const line = lines.find((l) => l.layer === "guardrail" && typeof l.data?.explanation === "string");
  return line ? (line.data.explanation as string) : null;
}

function chapterStatus(chapter: Chapter, steps: Record<string, StepState>, result: RunResult | null, phase: Phase): string {
  if (chapter.id === "trail") return result ? "done" : phase === "idle" ? "pending" : "pending";
  const states = chapter.steps.map((s) => steps[s]?.status).filter(Boolean) as string[];
  if (states.length === 0) return "pending";
  if (states.includes("blocked")) return "blocked";
  const last = steps[chapter.steps[chapter.steps.length - 1]]?.status;
  if (last === "done" || last === "skipped") return "done";
  // A finished run whose chapter steps all completed is done even if a
  // later step of that chapter was never reported.
  if (result && states.every((s) => s === "done" || s === "skipped")) return "done";
  return "active";
}

const STATUS_BADGE: Record<string, { label: string; className: string }> = {
  pending: { label: "waiting", className: "bg-muted text-muted-foreground" },
  active: { label: "in progress", className: "animate-pulse bg-chart-1/10 text-chart-1" },
  done: { label: "done", className: "bg-success/10 text-success" },
  blocked: { label: "stopped", className: "bg-warning/10 text-warning" },
};

function ChapterCard({
  index,
  chapter,
  status,
  steps,
  result,
  audit,
  traceId,
  payoutRefusedBy,
  replacedExplanation,
}: {
  index: number;
  chapter: Chapter;
  status: string;
  steps: Record<string, StepState>;
  result: RunResult | null;
  audit: AuditEntry[] | null;
  traceId: string | null;
  payoutRefusedBy: string | null;
  replacedExplanation: string | null;
}) {
  const badge = STATUS_BADGE[status] ?? STATUS_BADGE.pending;
  const summaries = chapter.steps.map((s) => steps[s]?.summary).filter(Boolean) as string[];
  const techNames = chapter.tech.map((id) => TECH.find((t) => t.id === id)?.name ?? id);

  return (
    <article
      className={`rounded-lg border bg-card p-4 transition-all duration-500 ${
        status === "active" ? "border-chart-1/50 shadow-md" : status === "pending" ? "border-border opacity-60" : "border-border"
      }`}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex items-start gap-3">
          <span
            className={`mt-0.5 inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold ${
              status === "done" ? "bg-success text-primary-foreground" : status === "blocked" ? "bg-warning text-primary-foreground" : "bg-secondary text-muted-foreground"
            }`}
          >
            {status === "done" ? "✓" : index}
          </span>
          <div>
            <h3 className="font-semibold text-card-foreground">{chapter.title}</h3>
            <p className="mt-1 text-sm text-muted-foreground">{chapter.narration}</p>
          </div>
        </div>
        <span className={`shrink-0 rounded-full px-2 py-0.5 text-[11px] font-medium ${badge.className}`}>{badge.label}</span>
      </div>

      {summaries.length > 0 && (
        <p className="mt-3 rounded-md bg-secondary px-3 py-2 text-sm font-medium text-card-foreground">{summaries.join(" · ")}</p>
      )}
      <ChapterDetail chapter={chapter} steps={steps} result={result} audit={audit} traceId={traceId}
        payoutRefusedBy={payoutRefusedBy}
        replacedExplanation={replacedExplanation}
      />

      <div className="mt-3 flex flex-wrap gap-1">
        {techNames.map((name) => (
          <span key={name} className="rounded border border-border px-1.5 py-0.5 text-[10px] font-medium text-muted-foreground">
            {name}
          </span>
        ))}
      </div>
    </article>
  );
}

function ChapterDetail({
  chapter,
  steps,
  result,
  audit,
  traceId,
  payoutRefusedBy,
  replacedExplanation,
}: {
  chapter: Chapter;
  steps: Record<string, StepState>;
  result: RunResult | null;
  audit: AuditEntry[] | null;
  traceId: string | null;
  payoutRefusedBy: string | null;
  replacedExplanation: string | null;
}) {
  const data = (id: string) => steps[id]?.data ?? {};

  if (chapter.id === "doc-guardrail") {
    if (steps.doc_guardrail?.status !== "done") return null;
    const d = data("doc_guardrail");
    const markers = stringList(d.markers);
    const docs = stringList(d.doc_types);
    if (!d.flagged) {
      return (
        <p className="mt-2 text-xs font-medium text-success">
          ✓ No instruction-like text in the documents — scanned before any agent read them.
        </p>
      );
    }
    return (
      <div className="mt-2 flex flex-col gap-1.5 text-xs">
        <p className="font-medium text-warning">
          ⚠ Instruction-like text found{docs.length > 0 ? ` in ${docs.join(", ")}` : ""}:
        </p>
        {markers.length > 0 && (
          <ul className="flex flex-wrap gap-1.5">
            {markers.map((m) => (
              <li key={m} className="rounded-full bg-warning/10 px-2 py-0.5 font-mono text-warning">
                {m}
              </li>
            ))}
          </ul>
        )}
        <p className="text-muted-foreground">
          <span className="font-medium text-card-foreground">This claim can never be auto-paid.</span> The agents still read the documents as
          untrusted data, but whatever they conclude, the payout decision goes to a human claims officer.
        </p>
      </div>
    );
  }

  if (chapter.id === "intake") {
    const items = (data("intake").line_items as { label: string; amount: number }[] | undefined) ?? [];
    if (items.length === 0) return null;
    return (
      <ul className="mt-2 grid gap-0.5 text-xs text-muted-foreground">
        {items.map((li, i) => (
          <li key={i} className="flex justify-between gap-3 tabular-nums">
            <span>{li.label}</span>
            <span>{formatInr(li.amount)}</span>
          </li>
        ))}
      </ul>
    );
  }

  if (chapter.id === "medical") {
    const d = data("medical");
    if (!d.icd10) return null;
    const flags = [
      ["stay justified", d.stay_justified],
      ["pre-existing suspected", d.pre_existing_suspected],
      ["excluded treatment", d.excluded_treatment],
    ] as const;
    return (
      <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
        {flags.map(([label, value]) => (
          <span key={label} className={`rounded-full px-2 py-0.5 ${value ? "bg-warning/10 text-warning" : "bg-muted text-muted-foreground"}`}>
            {label}: {value ? "yes" : "no"}
          </span>
        ))}
      </div>
    );
  }

  if (chapter.id === "settlement") {
    const deductions = (data("settlement").deductions as { amount: number; reason: string; clause_id: string }[] | undefined) ?? [];
    if (deductions.length === 0) return null;
    return (
      <ul className="mt-2 grid gap-0.5 text-xs text-muted-foreground">
        {deductions.map((d, i) => (
          <li key={i} className="tabular-nums">
            −{formatInr(d.amount)} · clause <span className="font-mono">{d.clause_id}</span> · {d.reason}
          </li>
        ))}
      </ul>
    );
  }

  if (chapter.id === "coverage") {
    const explanation = data("coverage").explanation as string | undefined;
    const checked = steps.explanation_guardrail?.status === "done";
    const guard = data("explanation_guardrail");
    const invented = numberList(guard.unexpected_amounts);
    const misstated = checked && (guard.ok === false || invented.length > 0);
    const replaced = checked && guard.replaced === true;
    if (!explanation && !checked) return null;
    if (!misstated && !replaced) {
      return (
        <>
          {explanation && <blockquote className="mt-2 border-l-2 border-border pl-3 text-sm italic text-muted-foreground">{explanation}</blockquote>}
          {checked && <p className="mt-2 text-xs font-medium text-success">✓ Every ₹ amount verified against the settlement.</p>}
        </>
      );
    }
    // The coverage step carries the agent's own draft; the replacement rides
    // on the guardrail's log event (and ends up in the final result).
    const replacement = replacedExplanation ?? (result?.explanation && result.explanation !== explanation ? result.explanation : null);
    return (
      <div className="mt-2 flex flex-col gap-2 text-xs">
        {misstated && explanation?.trim() && (
          <div>
            <p className="font-medium text-muted-foreground">The agent&apos;s draft — rejected:</p>
            <blockquote className="mt-1 border-l-2 border-destructive/50 pl-3 text-sm italic text-muted-foreground line-through decoration-destructive/40">
              {explanation}
            </blockquote>
          </div>
        )}
        {misstated ? (
          <p className="font-medium text-destructive">
            ✗ Amount(s) not in the settlement: {invented.length > 0 ? invented.map(formatInr).join(", ") : "unverified amount"}
          </p>
        ) : (
          <p className="font-medium text-warning">⚠ The coverage agent returned no explanation.</p>
        )}
        <p className={replaced ? "font-medium text-success" : "font-medium text-destructive"}>
          {replaced
            ? "Replaced before the policyholder could see it, with a summary built only from the settlement — every ₹ in it is a settlement figure."
            : "The explanation was NOT replaced — this should be investigated."}
        </p>
        {replaced && replacement && (
          <blockquote className="border-l-2 border-success/50 pl-3 text-sm italic text-muted-foreground">{replacement}</blockquote>
        )}
      </div>
    );
  }

  if (chapter.id === "fraud") {
    const flags = (data("fraud").flags as { type: string; severity: string; evidence_ref: string }[] | undefined) ?? [];
    if (flags.length === 0) return null;
    return (
      <ul className="mt-2 flex flex-col gap-1">
        {flags.map((f, i) => (
          <li key={i} className="flex items-center gap-2 text-sm">
            <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${severityStyle(f.severity)}`}>{f.severity}</span>
            {f.type}
          </li>
        ))}
      </ul>
    );
  }

  if (chapter.id === "tier") {
    const reasons = (data("tier").reasons as string[] | undefined) ?? [];
    if (reasons.length === 0) return null;
    return (
      <ul className="mt-2 list-disc pl-5 text-xs text-muted-foreground">
        {reasons.map((r) => (
          <li key={r}>{r}</li>
        ))}
      </ul>
    );
  }

  if (chapter.id === "payout" && payoutRefusedBy) {
    if (payoutRefusedBy === "GOV-004") {
      return (
        <p className="mt-2 rounded-md border border-warning/40 bg-warning/5 px-3 py-2 text-xs text-muted-foreground">
          <span className="font-medium text-card-foreground">Kill switch on — automated payouts are frozen by compliance.</span> Governance refused
          this payout under <span className="font-mono">GOV-004</span>: no redeploy, no prompt change. Nothing was paid, the refusal is in the
          hash-chained audit trail, and the claim went to a claims officer, whose approved payouts still go through.
        </p>
      );
    }
    return (
      <p className="mt-2 rounded-md border border-warning/40 bg-warning/5 px-3 py-2 text-xs text-muted-foreground">
        <span className="font-medium text-card-foreground">Governance refused the automatic payout.</span> Refused by{" "}
        <span className="font-mono">{payoutRefusedBy}</span>
        {RULE_TEXT[payoutRefusedBy] ? ` — ${RULE_TEXT[payoutRefusedBy]}` : ""}. Nothing was paid, and the claim fell back to a human officer.
      </p>
    );
  }

  if (chapter.id === "trail" && result) {
    const entries = audit ?? [];
    const denied = entries.filter((e) => e.policy_verdict !== "allowed" && e.policy_verdict !== "allow" && e.policy_verdict !== "success");
    return (
      <div className="mt-2 flex flex-col gap-2 text-xs text-muted-foreground">
        <p>
          <span className="font-medium text-foreground">{entries.length}</span> governed decisions recorded for this claim
          {denied.length > 0 && (
            <>
              , <span className="font-medium text-destructive">{denied.length} denied</span>
            </>
          )}
          .
        </p>
        {entries.length > 0 && (
          <div className="overflow-x-auto">
            <table className="w-full text-left">
              <tbody>
                {entries.slice(-8).map((e) => (
                  <tr key={e.trace_id} className="border-t border-border">
                    <td className="py-1 pr-2 font-mono">{e.trace_id.slice(0, 8)}</td>
                    <td className="py-1 pr-2">{e.agent_id}</td>
                    <td className="py-1 pr-2 font-mono">{e.tool_name}</td>
                    <td className={`py-1 ${e.violation_reason ? "text-destructive" : "text-success"}`}>{e.violation_reason ? e.violation_reason.split(":")[0] : e.policy_verdict}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        {traceId && (
          <p>
            Phoenix trace <span className="font-mono text-foreground">{traceId}</span> —{" "}
            <a href="http://localhost:6006" target="_blank" rel="noopener noreferrer" className="underline hover:text-foreground">
              open Phoenix ↗
            </a>
          </p>
        )}
      </div>
    );
  }

  return null;
}

function stringList(v: unknown): string[] {
  return Array.isArray(v) ? v.filter((x): x is string => typeof x === "string") : [];
}

function numberList(v: unknown): number[] {
  return Array.isArray(v) ? v.filter((x): x is number => typeof x === "number") : [];
}

function Outcome({ result, claimId, payoutRefusedBy }: { result: RunResult; claimId: string | null; payoutRefusedBy: string | null }) {
  const paid = result.final_state === "paid";
  const pending = result.final_state === "pending_human";
  return (
    <section
      className={`rounded-lg border p-5 ${paid ? "border-success/40 bg-success/5" : pending ? "border-warning/40 bg-warning/5" : "border-destructive/40 bg-destructive/5"}`}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 className="text-lg font-semibold text-card-foreground">
          {paid ? "Paid automatically" : pending ? "Waiting for a human decision" : humanizeStatus(result.final_state)}
        </h3>
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${statusStyle(result.final_state)}`}>
          {humanizeStatus(result.final_state)}
          {result.tier ? ` · ${result.tier}` : ""}
        </span>
      </div>
      {result.payable_amount != null && (
        <p className="mt-2 text-2xl font-semibold tabular-nums text-card-foreground">{formatInr(result.payable_amount)}</p>
      )}
      <p className="mt-1 text-sm text-muted-foreground">
        {paid
          ? "Every rule passed, the governance layer allowed the payout, and a mock payment was recorded to the account on file."
          : pending && payoutRefusedBy === "GOV-004"
            ? "This claim qualified for automatic payment (T2), but compliance has frozen automated payouts (GOV-004 kill switch). The payout was refused and audited; a claims officer now makes the call."
            : pending
              ? "The agents did their work but are not allowed to finish this one alone. A claims officer now sees the findings, flags and clauses and makes the call."
              : "The claim was stopped before any agent ran — the policyholder is asked to resubmit."}
      </p>
      {claimId && (
        <div className="mt-3 flex flex-wrap gap-3 text-sm">
          <Link href="/pipeline" className="underline hover:text-foreground">
            See all agent outputs (Pipeline)
          </Link>
          {pending && (
            <Link href="/officer" className="underline hover:text-foreground">
              Decide it as the officer
            </Link>
          )}
          <Link href="/compliance" className="underline hover:text-foreground">
            Compliance audit log
          </Link>
        </div>
      )}
    </section>
  );
}

function AttackChapter({
  poisoned,
  phase,
  steps,
  attack,
  onRun,
}: {
  poisoned: boolean;
  phase: Phase;
  steps: Record<string, StepState>;
  attack: AttackResult | null;
  onRun: () => void;
}) {
  return (
    <section className={`rounded-lg border p-5 ${poisoned ? "border-destructive/40 bg-destructive/5" : "border-border bg-card"}`}>
      <h3 className="font-semibold text-card-foreground">What if the AI had been fooled?</h3>
      <p className="mt-1 text-sm text-muted-foreground">
        {poisoned
          ? "This claim's discharge summary hid an instruction to pay ₹4,50,000 to account 9988776655. The agents ignored it — but safety can't depend on an AI resisting a trick. So now we pretend an agent did obey it, and send the attacker's requests as real tool calls."
          : "Safety can't depend on an AI never being tricked. Replay the classic attack — pay ₹4,50,000 to account 9988776655 and read raw medical records — as real tool calls against this claim, and watch the governance layer refuse them."}
      </p>
      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        {ATTACK_STEPS.map((a) => {
          const state = steps[a.id];
          const blocked = state?.status === "blocked";
          return (
            <div
              key={a.id}
              className={`rounded-md border p-3 text-sm ${
                blocked ? "border-success/40 bg-success/5" : state?.status === "active" ? "animate-pulse border-chart-1/40" : state ? "border-destructive/50 bg-destructive/10" : "border-border bg-card"
              }`}
            >
              <p className="font-medium text-card-foreground">{a.title}</p>
              <p className="mt-0.5 text-xs text-muted-foreground">{state?.summary ?? `Expected: ${a.expected}`}</p>
              {blocked && <p className="mt-1 text-xs font-semibold text-success">🛡 Blocked — nothing was paid or read</p>}
            </div>
          );
        })}
      </div>
      {attack && (
        <p className={`mt-3 text-sm font-medium ${attack.all_blocked ? "text-success" : "text-destructive"}`}>
          {attack.all_blocked
            ? "Every attempt was refused by fixed rules written in code, not by the AI's judgement. The governance refusals (PAY-001, PAY-002, DATA-001) are in the audit trail in “The paper trail” above; the token service's GOV-003 refusal is recorded in the Phoenix trace."
            : "At least one attempt was not refused. This is a security failure and should be investigated."}
        </p>
      )}
      {phase !== "attacked" && (
        <button
          type="button"
          onClick={onRun}
          disabled={phase !== "done"}
          className="mt-4 rounded-md bg-destructive px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
        >
          {phase === "attacking" ? "Attacking…" : "Run the red-team attack"}
        </button>
      )}
    </section>
  );
}

function Intro() {
  return (
    <section className="rounded-xl border border-border bg-card shadow-sm p-6">
      <span className="text-xs font-semibold uppercase tracking-[0.12em] text-chart-1">Live Run · real backend</span>
      <h1 className="mt-1 text-2xl font-semibold tracking-tight text-card-foreground">
        A claim, from hospital paperwork to payout — live
      </h1>
      <p className="mt-2 max-w-3xl text-sm text-muted-foreground">
        Today, officers review every reimbursement claim by hand: slow, inconsistent and hard to audit. ClaimGuard hands
        that work to five AI agents — but because they touch medical records and money, every step they take runs through
        a governance layer that can say no, is logged in a tamper-evident audit trail, and is traced end to end. Pick a
        claim below and watch the real backend work: each step explained on the left, every backend operation on the right.
      </p>
      <div className="mt-4 grid gap-3 text-sm sm:grid-cols-3">
        <Pillar title="Least privilege" text="Each agent gets a signed, single-purpose token that expires in minutes. Only one agent ever sees medical text." />
        <Pillar title="Humans decide the hard cases" text="Big payouts, fraud flags, exclusions and every rejection go to a claims officer — by policy, not by prompt." />
        <Pillar title="Nothing is invisible" text="Every allow/deny is hash-chained in the audit log; every claim is one redacted trace in Phoenix." />
      </div>
    </section>
  );
}

function Pillar({ title, text }: { title: string; text: string }) {
  return (
    <div className="rounded-md bg-secondary p-3">
      <p className="font-medium text-card-foreground">{title}</p>
      <p className="mt-1 text-xs text-muted-foreground">{text}</p>
    </div>
  );
}

function BuildJourney() {
  return (
    <section className="rounded-xl border border-border bg-card shadow-sm p-5">
      <h2 className="font-semibold text-card-foreground">How it was built</h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Delivered milestone by milestone, security core first — each ending in something demonstrable.
      </p>
      <ol className="mt-4 grid gap-2 sm:grid-cols-2">
        {MILESTONES.map((m) => (
          <li key={m.id} className="flex gap-3 rounded-md border border-border p-3">
            <span className="font-mono text-xs font-semibold text-chart-1">{m.id}</span>
            <div>
              <p className="text-sm font-medium text-card-foreground">{m.title}</p>
              <p className="text-xs text-muted-foreground">{m.detail}</p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
