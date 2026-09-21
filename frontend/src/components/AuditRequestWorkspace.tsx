"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { ArrowRight, Lightbulb, Play } from "lucide-react";
import { ErrorBanner } from "@/components/ErrorBanner";
import { UseCaseCard } from "@/components/UseCaseCard";
import { api, ApiError } from "@/lib/api";
import type { UseCase } from "@/lib/types";

const EXAMPLES = [
  "Provide AP Cost Drill for August 2026, SOB 101, NAC 5000–5999.",
  "Prepare trade payables ageing schedule as at 30 June 2026.",
  "Provide alternate testing documents for ABC Ltd, Invoice INV-12345.",
];

export function AuditRequestWorkspace({
  useCases,
  backendUnavailable = false,
}: {
  useCases: UseCase[];
  backendUnavailable?: boolean;
}) {
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(event: React.FormEvent) {
    event.preventDefault();
    if (submitting) return;

    const trimmed = query.trim();
    if (!trimmed) {
      // Wording from the app flow spec's missing-parameters error state.
      setError("Required inputs are missing. Please provide the highlighted values.");
      document.getElementById("audit-requirement")?.focus();
      return;
    }

    setSubmitting(true);
    setError(null);
    try {
      const { request_id } = await api.createRequest(trimmed);
      // Start the workflow, then hand off to the detail page, which polls.
      await api.runRequest(request_id);
      router.push(`/requests/${request_id}`);
    } catch (err) {
      setError(
        err instanceof ApiError
          ? err.message
          : "The request could not be submitted.",
      );
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto max-w-form px-8 py-8">
      {backendUnavailable && (
        <div className="mb-6">
          <ErrorBanner
            title="Backend not reachable"
            message="Start the API with: uvicorn app.main:app --port 8000"
            tone="warning"
          />
        </div>
      )}

      {error && (
        <div className="mb-6">
          <ErrorBanner title="Something went wrong" message={error} />
        </div>
      )}

      <form onSubmit={handleSubmit} className="card p-6">
        <label
          htmlFor="audit-requirement"
          className="block text-sm font-semibold text-ink"
        >
          Audit Requirement
        </label>
        <textarea
          id="audit-requirement"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          rows={4}
          placeholder="Example: Provide AP Cost Drill for August 2026, SOB 101, NAC 5000&#8211;5999."
          aria-describedby="audit-requirement-help"
          className="field mt-3 resize-y leading-relaxed"
        />
        <p id="audit-requirement-help" className="mt-3 text-[13px] text-ink-muted">
          Describe your audit requirement in natural language. You do not need to
          specify databases or technical systems.
        </p>

        <div className="mt-5 flex justify-end">
          {/* Stays enabled when empty so the call to action reads as the
              primary action; an empty submit surfaces the missing-input
              message instead of presenting a dead control. */}
          <button type="submit" disabled={submitting} className="btn-primary">
            {submitting ? (
              <>
                <span
                  className="h-4 w-4 animate-spin rounded-full border-2 border-white/40 border-t-white"
                  aria-hidden="true"
                />
                Starting&#8230;
              </>
            ) : (
              <>
                <Play className="h-4 w-4" aria-hidden="true" />
                Start Retrieval
              </>
            )}
          </button>
        </div>
      </form>

      <section className="mt-10" aria-labelledby="supported-heading">
        <h2 id="supported-heading" className="section-heading">
          Supported Audit Requirements
        </h2>
        <p className="mt-1 text-[14px] text-ink-muted">
          This system supports the following four audit use cases.
        </p>

        <div className="mt-5 grid gap-5 md:grid-cols-2">
          {useCases.map((useCase) => (
            <UseCaseCard key={useCase.use_case_id} useCase={useCase} />
          ))}
        </div>
      </section>

      <section className="card mt-8 p-6" aria-labelledby="examples-heading">
        <h2
          id="examples-heading"
          className="flex items-center gap-2 text-[15px] font-semibold text-ink"
        >
          <Lightbulb className="h-4 w-4 text-ink-muted" aria-hidden="true" />
          Example Requests
        </h2>
        <ul className="mt-4 space-y-3">
          {EXAMPLES.map((example) => (
            <li key={example}>
              <button
                type="button"
                onClick={() => setQuery(example)}
                className="flex w-full items-center gap-3 rounded-control bg-canvas px-4 py-3.5 text-left text-[14px] text-primary transition-colors hover:bg-primary-faint"
              >
                <ArrowRight className="h-4 w-4 shrink-0" aria-hidden="true" />
                <span>{example}</span>
              </button>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
