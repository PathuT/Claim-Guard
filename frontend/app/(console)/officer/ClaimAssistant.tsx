"use client";

import { useState } from "react";
import { ApiError, type AssistantMessage, askClaimAssistant } from "@/lib/api";

const SUGGESTIONS = [
  "Why is this claim with an officer instead of auto-paid?",
  "Explain the deductions and the payable amount.",
  "What do the fraud signals mean?",
];

// Matches the backend's cap (agents/officer_assistant.py MAX_HISTORY_MESSAGES).
const HISTORY_SENT = 6;

type Turn = AssistantMessage & { replaced?: boolean };

/** ADR-014: read-only Q&A about the open claim. Answers come only from the
 * settlement, flags and structured finding already shown above; any ₹ amount
 * not in the settlement makes the backend replace the answer. */
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
      setTurns((t) => [...t, { role: "assistant", content: r.answer, replaced: r.replaced }]);
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
        Read-only. Answers use only the settlement, flags and findings shown above, not the discharge summary, the
        medical reviewer&apos;s note or bank details. Every ₹ amount is checked against the settlement.
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
            </li>
          ))}
          {pending && <li className="self-start text-xs text-muted-foreground">Thinking…</li>}
        </ul>
      )}

      {turns.length === 0 && (
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
      )}

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
          placeholder="e.g. Which clause caused the biggest deduction?"
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
