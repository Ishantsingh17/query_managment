"use client";

import { useState } from "react";
import { CheckCircle2, CornerDownLeft, MessageCircleQuestion, Send } from "lucide-react";
import { api, ApiError } from "@/lib/api";
import type { AuditRequestDetail } from "@/lib/types";

/**
 * The clarifying turn.
 *
 * A request can be understood and still be unsearchable: a cost drill needs
 * SOB, NAC range and report type to select the right documents, and searching
 * without them would return confidently wrong evidence. Rather than fail, the
 * workflow stops here and asks. The answer is free text and is re-parsed
 * together with the original request, so a partial answer simply narrows the
 * question rather than restarting it.
 */
export function ClarificationPanel({
  detail,
  onAnswered,
}: {
  detail: AuditRequestDetail;
  onAnswered: () => void;
}) {
  const [answer, setAnswer] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function send(event: React.FormEvent) {
    event.preventDefault();
    const trimmed = answer.trim();
    if (!trimmed || sending) return;

    setSending(true);
    setError(null);
    try {
      await api.clarify(detail.request_id, trimmed);
      setAnswer("");
      onAnswered();
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : "The answer could not be submitted.",
      );
    } finally {
      setSending(false);
    }
  }

  return (
    <section className="card border-warning-border">
      <div className="card-header border-warning-border bg-warning-soft">
        <h2 className="flex items-center gap-2 text-[17px] font-semibold text-warning-text">
          <MessageCircleQuestion className="h-5 w-5" aria-hidden="true" />
          More information needed
        </h2>
        <p className="mt-0.5 text-[13px] text-warning-text">
          The request was understood, but these inputs are required before any
          source system is searched.
        </p>
      </div>

      <div className="p-6">
        {/* Prior answers, so the exchange reads as a conversation. */}
        {detail.clarifications.length > 0 && (
          <ul className="mb-5 space-y-2">
            {detail.clarifications.map((entry, index) => (
              <li
                key={index}
                className="flex items-start gap-2.5 rounded-control bg-canvas px-4 py-2.5"
              >
                <CheckCircle2
                  className="mt-0.5 h-4 w-4 shrink-0 text-success"
                  aria-hidden="true"
                />
                <span className="text-[13px] text-ink-soft">
                  You answered: <span className="font-medium text-ink">{entry.answer}</span>
                </span>
              </li>
            ))}
          </ul>
        )}

        <p className="text-[15px] leading-relaxed text-ink">
          {detail.clarification_question}
        </p>

        {detail.missing_parameters.length > 0 && (
          <ul className="mt-3 flex flex-wrap gap-2" aria-label="Required inputs">
            {detail.missing_parameters.map((parameter) => (
              <li
                key={parameter.key}
                className="inline-flex items-center rounded-md bg-warning-soft px-2.5 py-1 text-meta font-semibold text-warning-text"
              >
                {parameter.label}
              </li>
            ))}
          </ul>
        )}

        <form onSubmit={send} className="mt-5">
          <label htmlFor="clarification-answer" className="sr-only">
            Your answer
          </label>
          <div className="flex gap-3">
            <input
              id="clarification-answer"
              value={answer}
              onChange={(event) => setAnswer(event.target.value)}
              placeholder={
                detail.clarification_example
                  ? `e.g. ${detail.clarification_example}`
                  : "Type your answer…"
              }
              autoComplete="off"
              className="field flex-1"
            />
            <button type="submit" disabled={!answer.trim() || sending} className="btn-primary">
              {sending ? (
                <>
                  <span
                    className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
                    aria-hidden="true"
                  />
                  Sending…
                </>
              ) : (
                <>
                  <Send className="h-4 w-4" aria-hidden="true" />
                  Send
                </>
              )}
            </button>
          </div>

          <p className="mt-2.5 flex items-center gap-1.5 text-meta text-ink-muted">
            <CornerDownLeft className="h-3.5 w-3.5" aria-hidden="true" />
            Answer in plain language. Retrieval continues automatically once
            every required input is known.
          </p>
        </form>

        {error && (
          <p role="alert" className="mt-4 text-[13px] font-medium text-danger-text">
            {error}
          </p>
        )}
      </div>
    </section>
  );
}
