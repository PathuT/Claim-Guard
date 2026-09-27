"use client";

import Link from "next/link";
import { useRef, useState } from "react";
import {
  ApiError,
  type AuditEntry,
  type LiveEvent,
  type NewClaimFields,
  type SamplePack,
  fetchSampleFile,
  getClaimAudit,
  listSamplePacks,
  streamAttack,
  streamClaimRun,
  submitNewClaim,
} from "@/lib/api";
import { formatInr, humanizeStatus, severityStyle, statusStyle } from "@/lib/format";
import { ATTACK_STEPS, CHAPTERS, type Chapter, MILESTONES, TECH } from "@/lib/liveRun";
import { EvalsPanel } from "./EvalsPanel";
import { LiveConsole, type LogLine, TechStrip } from "./LiveConsole";
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

  const startedAt = useRef(0);
  const nextId = useRef(0);

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
  }

  function log(layer: string, title: string, detail: string | null = null, level = "info", kind: "log" | "trace" = "log") {
    const line: LogLine = { id: nextId.current++, t: performance.now() - startedAt.current, kind, layer, level, title, detail };
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
        log(event.layer, event.title, event.detail, event.level, event.kind);
        break;
      case "step":
        setStep(event.step, event.status, event.summary, event.data);
        break;
      case "result":
        setTraceId(event.trace_id);
        setElapsedMs(event.elapsed_ms);
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
    try {
      await streamClaimRun(id, (event) =>
        handleEvent(event, (r) => {
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

  return (
    <div className="relative left-1/2 flex w-[min(1400px,calc(100vw-2rem))] -translate-x-1/2 flex-col gap-6">
      <Intro />

      <StartPanel disabled={busy} onSamplePack={handleSamplePack} onUpload={handleUpload} onReplay={handleReplay} />

      {started && (
        <>
          <section className="flex flex-col gap-3 rounded-lg border border-border bg-card p-4">
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
            <TechStrip lines={lines} />
          </section>

          <SystemFlow lines={lines} live={busy} />

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
                />
              ))}
              {result && <Outcome result={result} claimId={claimId} />}
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
                  {panel === "log" ? <LiveConsole lines={lines} running={busy} /> : <Requirements lines={lines} />}
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

function chapterStatus(chapter: Chapter, steps: Record<string, StepState>, result: RunResult | null, phase: Phase): string {
  if (chapter.id === "trail") return result ? "done" : phase === "idle" ? "pending" : "pending";
  const states = chapter.steps.map((s) => steps[s]?.status).filter(Boolean) as string[];
  if (states.length === 0) return "pending";
  if (states.includes("blocked")) return "blocked";
  const last = steps[chapter.steps[chapter.steps.length - 1]]?.status;
  if (last === "done" || last === "skipped") return "done";
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
}: {
  index: number;
  chapter: Chapter;
  status: string;
  steps: Record<string, StepState>;
  result: RunResult | null;
  audit: AuditEntry[] | null;
  traceId: string | null;
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
      <ChapterDetail chapter={chapter} steps={steps} result={result} audit={audit} traceId={traceId} />

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
}: {
  chapter: Chapter;
  steps: Record<string, StepState>;
  result: RunResult | null;
  audit: AuditEntry[] | null;
  traceId: string | null;
}) {
  const data = (id: string) => steps[id]?.data ?? {};

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
    if (!explanation) return null;
    return <blockquote className="mt-2 border-l-2 border-border pl-3 text-sm italic text-muted-foreground">{explanation}</blockquote>;
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

function Outcome({ result, claimId }: { result: RunResult; claimId: string | null }) {
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
    <section className="rounded-lg border border-border bg-card p-6">
      <span className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Kaveri Health Assurance · ClaimGuard</span>
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
    <section className="rounded-lg border border-border bg-card p-5">
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
