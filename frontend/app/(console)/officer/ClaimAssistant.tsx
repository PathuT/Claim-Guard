"use client";

import { useState } from "react";
import { ApiError, type AssistantMessage, type AssistantStep, askClaimAssistant } from "@/lib/api";

const SUGGESTIONS = [
  "Why is this claim with an officer instead of auto-paid?",
  "Explain the deductions and the payable amount.",
  "What do the fraud signals mean?",
  "Summarise the medical finding.",
  "What was billed, and how long was the stay?",
  "Which clause caused the biggest deduction?",
  "How much sum insured is left?",
  "Is anything blocking an approval?",
];

// Matches the backend's cap (agents/officer_assistant.py MAX_HISTORY_MESSAGES).
const HISTORY_SENT = 6;

const TOOL_LABELS: Record<string, string> = {
  get_claim_overview: "overview",
  get_settlement: "settlement",
  get_fraud_signals: "fraud signals",
  get_medical_finding: "medical finding",
  get_bill: "bill",
  get_routing_reasons: "routing reasons",
};

type Turn = AssistantMessage & { replaced?: boolean; steps?: AssistantStep[] };

/** ADR-014: an Agno agent with six read-only tools, scoped to the open claim.
 * Every tool call is checked and audited by AGT; the panel shows which ones
 * the agent used. Any ₹ amount not in the settlement makes the backend
 * replace the answer. */
export function ClaimAssistant({ claimId }: { claimId: string }) {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function ask(text: string) {
    const q = text.trim();
    if (!q || pending) return;
    setPending(true);
    setError(null);
    const history = turns.slice(-HISTORY_SENT).map(({ role, content }) => ({ role, content }));
    setTurns((t) => [...t, { role: "officer", content: q }]);
    setQuestion("");
    try {
      const r = await askClaimAssistant(claimId, q, history);
      setTurns((t) => [...t, { role: "assistant", content: r.answer, replaced: r.replaced, steps: r.steps }]);
    } catch (err) {
      setTurns((t) => t.slice(0, -1));
      setQuestion(q);
      setError(err instanceof ApiError ? `${err.message}${err.reasonCode ? ` (${err.reasonCode})` : ""}` : "Something went wrong.");
    } finally {
      setPending(false);
    }
  }

  return (
    <div className="rounded-md border border-border p-4">
      <h3 className="text-sm font-medium text-card-foreground">Ask about this claim</h3>
      <p className="mt-1 text-xs text-muted-foreground">
        An agent looks up what it needs with read-only tools, each checked and audited by AGT. It never sees the
        discharge summary, the medical reviewer&apos;s note or bank details, and every ₹ amount is checked against the
        settlement. It cannot approve, reject or pay.
      </p>

      {turns.length > 0 && (
        <ul className="mt-3 flex flex-col gap-2" aria-live="polite">
          {turns.map((t, i) => (
            <li
              key={i}
              className={
                t.role === "officer"
                  ? "self-end max-w-[85%] rounded-md bg-primary/10 px-3 py-2 text-sm text-card-foreground"
                  : "self-start max-w-[85%] rounded-md bg-secondary px-3 py-2 text-sm text-card-foreground"
              }
            >
              <span className="whitespace-pre-wrap break-words">{t.content}</span>
              {t.replaced && (
                <span className="mt-1 block text-xs text-warning">Answer replaced: it quoted an amount not in the settlement.</span>
              )}
              {t.steps && (
                <span className="mt-2 flex flex-wrap items-center gap-1 text-[11px] text-muted-foreground">
                  {t.steps.length === 0 ? (
                    "Answered without looking anything up."
                  ) : (
                    <>
                      Looked up:
                      {t.steps.map((s, j) => (
                        <span
                          key={j}
                          title={s.decision === "allow" ? "Allowed and audited by AGT" : `Denied by AGT (${s.rule_id})`}
                          className={
                            s.decision === "allow"
                              ? "rounded-full bg-success/10 px-2 py-0.5 text-success"
                              : "rounded-full bg-destructive/10 px-2 py-0.5 text-destructive"
                          }
                        >
                          {TOOL_LABELS[s.tool] ?? s.tool} {s.decision === "allow" ? "✓" : `✕ ${s.rule_id}`}
                        </span>
                      ))}
                    </>
                  )}
                </span>
              )}
            </li>
          ))}
          {pending && <li className="self-start text-xs text-muted-foreground">Looking it up…</li>}
        </ul>
      )}

      <div className="mt-3 flex flex-wrap gap-2">
        {SUGGESTIONS.map((s) => (
          <button
            key={s}
            type="button"
            disabled={pending}
            onClick={() => ask(s)}
            className="rounded-full border border-border px-3 py-1 text-xs text-muted-foreground hover:border-primary hover:text-card-foreground disabled:opacity-50"
          >
            {s}
          </button>
        ))}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault();
          ask(question);
        }}
        className="mt-3 flex gap-2"
      >
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          maxLength={1000}
          placeholder="Ask anything about this claim"
          aria-label="Question about this claim"
          className="min-w-0 flex-1 rounded-md border border-border bg-background px-2 py-1.5 text-sm outline-none focus:border-primary"
        />
        <button
          type="submit"
          disabled={pending || !question.trim()}
          className="rounded-md bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:opacity-90 disabled:opacity-50"
        >
          {pending ? "Asking…" : "Ask"}
        </button>
      </form>
      {error && <p className="mt-2 text-sm text-destructive">{error}</p>}
    </div>
  );
}
