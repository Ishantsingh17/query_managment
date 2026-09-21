"use client";

import { use, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  FileText,
  RefreshCw,
  ShieldCheck,
  UserRoundCheck,
  XCircle,
} from "lucide-react";
import { EmptyState, ErrorBanner, LoadingState } from "@/components/ErrorBanner";
import { EvidenceTable } from "@/components/EvidenceTable";
import { StatCard } from "@/components/StatCard";
import { ValidationPanel } from "@/components/ValidationPanel";
import { api, ApiError } from "@/lib/api";
import { useRequestPolling } from "@/lib/useRequestPolling";
import type { ReviewActionType } from "@/lib/types";

export default function ReviewPage({
  params,
}: {
  params: Promise<{ requestId: string }>;
}) {
  const { requestId } = use(params);
  const router = useRouter();
  const { detail, error, loading, refresh } = useRequestPolling(requestId);

  const [comment, setComment] = useState("");
  const [pending, setPending] = useState<ReviewActionType | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  async function submit(action: ReviewActionType) {
    if (pending) return;
    setPending(action);
    setActionError(null);
    try {
      await api.review(requestId, action, comment);
      if (action === "APPROVE") {
        router.push(`/requests/${requestId}/package`);
        return;
      }
      // Reject and retry both return to the request detail screen.
      router.push(`/requests/${requestId}`);
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : "The action could not be completed.",
      );
      setPending(null);
      void refresh();
    }
  }

  if (loading && !detail) {
    return (
      <div className="px-8 py-8">
        <LoadingState label="Loading package…" />
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="mx-auto max-w-detail px-8 py-8">
        {error ? (
          <ErrorBanner title="Could not load this request" message={error} />
        ) : (
          <EmptyState title="Request not found" />
        )}
      </div>
    );
  }

  const validation = detail.validation;
  const complete = validation?.validation_status === "COMPLETE";
  const missingCount =
    detail.evidence_required_count - detail.evidence_found_count;
  const alreadyReviewed = ["APPROVED", "REJECTED"].includes(detail.status);

  return (
    <div className="mx-auto max-w-detail px-8 py-8">
      {/* --- header ------------------------------------------------------ */}
      <div className="flex flex-wrap items-baseline gap-2 text-[13px] text-ink-muted">
        <Link
          href={`/requests/${requestId}`}
          className="inline-flex items-center gap-1.5 hover:text-primary"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden="true" />
          Back to Request
        </Link>
        <span aria-hidden="true">/</span>
        <span>{detail.request_id}</span>
      </div>

      <h1 className="mt-2 text-[28px] font-bold leading-tight tracking-[-0.01em] text-ink">
        Evidence Package Ready for Review
      </h1>
      <p className="mt-1.5 text-[15px] text-ink-muted">
        Review the retrieved evidence and validation results before approval.
      </p>

      {/* --- stat tiles -------------------------------------------------- */}
      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
        <StatCard
          label="Required Evidence"
          value={detail.evidence_required_count}
          icon="required"
        />
        <StatCard
          label="Found"
          value={detail.evidence_found_count}
          icon="found"
          tone={detail.evidence_found_count > 0 ? "success" : "neutral"}
        />
        <StatCard
          label="Missing"
          value={Math.max(missingCount, 0)}
          icon="missing"
          tone={missingCount > 0 ? "warning" : "neutral"}
        />
        <StatCard
          label="Validation"
          value={
            validation
              ? validation.validation_status.replace(/_/g, " ")
              : "Pending"
          }
          icon="validation"
          tone={complete ? "success" : validation ? "warning" : "neutral"}
        />
        <StatCard
          label="Retrieval Sources"
          value={detail.databases_searched}
          icon="sources"
        />
        <StatCard label="Retry Count" value={detail.retry_count} icon="retries" />
      </div>

      {actionError && (
        <div className="mt-6">
          <ErrorBanner title="Action failed" message={actionError} />
        </div>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-[minmax(0,2fr)_minmax(0,1fr)]">
        {/* --- left column --------------------------------------------- */}
        <div className="min-w-0 space-y-6">
          <section className="card">
            <div className="card-header">
              <h2 className="card-title">Query Summary</h2>
            </div>
            <div className="grid gap-6 p-6 md:grid-cols-2">
              <div>
                <p className="label-caps">Original Query</p>
                <p className="mt-2.5 rounded-control bg-canvas px-4 py-3 text-[14px] italic leading-relaxed text-ink">
                  &ldquo;{detail.raw_query}&rdquo;
                </p>
              </div>
              <div>
                <p className="label-caps">Parsed Query</p>
                <dl className="mt-2.5 rounded-control bg-canvas px-4 py-3">
                  <div className="flex justify-between gap-4 py-1">
                    <dt className="text-[13px] text-ink-muted">Use Case</dt>
                    <dd className="text-right text-[13px] font-semibold text-ink">
                      {detail.use_case_id} — {detail.requirement_name}
                    </dd>
                  </div>
                  {detail.parameters.map((parameter) => (
                    <div
                      key={parameter.key}
                      className="flex justify-between gap-4 py-1"
                    >
                      <dt className="text-[13px] text-ink-muted">
                        {parameter.label}
                      </dt>
                      <dd className="text-right text-[13px] font-semibold text-ink">
                        {parameter.value}
                      </dd>
                    </div>
                  ))}
                </dl>
              </div>
            </div>
          </section>

          <EvidenceTable
            requestId={requestId}
            rows={detail.retrieved_evidence}
            validated={complete}
          />

          {detail.database_attempts.length > 0 && (
            <section className="card">
              <div className="card-header">
                <h2 className="card-title">Search &amp; Retry Summary</h2>
              </div>
              <div className="grid gap-4 p-6 sm:grid-cols-2 lg:grid-cols-4">
                {detail.database_attempts.map((attempt) => (
                  <div
                    key={attempt.database_id}
                    className="rounded-control border border-line bg-canvas p-4"
                  >
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[14px] font-semibold text-ink">
                        {attempt.name || attempt.database_id}
                      </span>
                      <span
                        className={`text-meta font-semibold ${
                          attempt.status === "COMPLETED"
                            ? "text-success-text"
                            : "text-danger-text"
                        }`}
                      >
                        {attempt.status === "COMPLETED"
                          ? "Completed"
                          : "Unavailable"}
                      </span>
                    </div>
                    <p className="mt-2 text-[13px] text-ink-muted">
                      {attempt.result_count === 1
                        ? "1 match"
                        : `${attempt.result_count} matches`}
                    </p>
                    {attempt.newly_found.length > 0 && (
                      <p className="mt-0.5 text-[13px] text-ink-soft">
                        {attempt.newly_found.join(", ")}
                      </p>
                    )}
                  </div>
                ))}
              </div>
              {detail.retry_note && (
                <p className="mx-6 mb-6 flex items-start gap-2 rounded-control bg-canvas px-4 py-3 text-[13px] text-ink-muted">
                  <RefreshCw className="mt-px h-4 w-4 shrink-0" aria-hidden="true" />
                  {detail.retry_note}
                </p>
              )}
            </section>
          )}

          {validation && (
            <ValidationPanel
              validation={validation}
              retryCount={detail.retry_count}
              retryNote={null}
              missingEvidence={detail.missing_evidence}
              showHeader
            />
          )}
        </div>

        {/* --- right column: reviewer action --------------------------- */}
        <div className="min-w-0 space-y-6">
          <section className="card p-6">
            <h2 className="flex items-center gap-2 text-[17px] font-semibold text-ink">
              <UserRoundCheck className="h-5 w-5 text-ink-muted" aria-hidden="true" />
              Reviewer Action
            </h2>
            <p className="mt-1 text-[13px] text-ink-muted">
              AP Reviewer · {detail.request_id}
            </p>

            <hr className="my-5 border-line" />

            <div
              className={`flex items-start gap-3 rounded-control border px-4 py-3.5 ${
                complete
                  ? "border-success-border bg-success-soft"
                  : "border-warning-border bg-warning-soft"
              }`}
            >
              {complete ? (
                <ShieldCheck
                  className="mt-0.5 h-5 w-5 shrink-0 text-success-text"
                  aria-hidden="true"
                />
              ) : (
                <AlertTriangle
                  className="mt-0.5 h-5 w-5 shrink-0 text-warning-text"
                  aria-hidden="true"
                />
              )}
              <div className="min-w-0">
                <p
                  className={`text-[14px] font-semibold ${
                    complete ? "text-success-text" : "text-warning-text"
                  }`}
                >
                  {complete ? "Package is Complete" : "Package Needs Attention"}
                </p>
                <p
                  className={`mt-0.5 text-[13px] leading-relaxed ${
                    complete ? "text-success-text" : "text-warning-text"
                  }`}
                >
                  {complete
                    ? "All required evidence found and validated."
                    : (validation?.message ??
                      "Some required evidence is still outstanding.")}
                </p>
              </div>
            </div>

            {alreadyReviewed ? (
              <div className="mt-5 rounded-control bg-canvas px-4 py-3.5">
                <p className="text-[13px] text-ink-muted">
                  This package was already{" "}
                  <span className="font-semibold text-ink">
                    {detail.status === "APPROVED" ? "approved" : "rejected"}
                  </span>
                  {detail.reviewer_name ? ` by ${detail.reviewer_name}` : ""}.
                </p>
                {detail.status === "APPROVED" && (
                  <Link
                    href={`/requests/${requestId}/package`}
                    className="btn-primary mt-3 w-full"
                  >
                    Open Package
                  </Link>
                )}
              </div>
            ) : (
              <>
                <div className="mt-5 space-y-3">
                  <button
                    type="button"
                    onClick={() => submit("APPROVE")}
                    disabled={pending !== null}
                    className="btn-primary w-full"
                  >
                    <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
                    {pending === "APPROVE" ? "Approving…" : "Approve Package"}
                  </button>
                  <button
                    type="button"
                    onClick={() => submit("RETRY")}
                    disabled={pending !== null}
                    className="btn-outline w-full"
                  >
                    <RefreshCw className="h-4 w-4" aria-hidden="true" />
                    {pending === "RETRY" ? "Retrying…" : "Request Retry"}
                  </button>
                  <button
                    type="button"
                    onClick={() => submit("REJECT")}
                    disabled={pending !== null}
                    className="btn-danger w-full"
                  >
                    <XCircle className="h-4 w-4" aria-hidden="true" />
                    {pending === "REJECT" ? "Rejecting…" : "Reject"}
                  </button>
                </div>

                <div className="mt-5">
                  <label
                    htmlFor="reviewer-comments"
                    className="block text-[13px] font-medium text-ink-soft"
                  >
                    Reviewer Comments
                  </label>
                  <textarea
                    id="reviewer-comments"
                    rows={3}
                    value={comment}
                    onChange={(event) => setComment(event.target.value)}
                    placeholder="Add comments (optional)…"
                    className="field mt-2 resize-y"
                  />
                </div>

                <p className="mt-4 text-[13px] leading-relaxed text-ink-muted">
                  Approval will generate the final audit evidence package.
                </p>
              </>
            )}
          </section>

          {detail.retrieved_evidence.length > 0 && (
            <section className="card p-6">
              <h2 className="label-caps">Package Contents Preview</h2>
              <ul className="mt-4 divide-y divide-line border-t border-line">
                {detail.retrieved_evidence.map((row) => (
                  <li
                    key={row.evidence_id}
                    className="flex items-center gap-3 py-3"
                  >
                    <FileText
                      className="h-4 w-4 shrink-0 text-primary"
                      aria-hidden="true"
                    />
                    <span className="min-w-0 flex-1 truncate text-[13px] text-ink">
                      {row.staged_file_path
                        ? row.staged_file_path.split("/").pop()
                        : row.document_type_label}
                    </span>
                  </li>
                ))}
              </ul>
            </section>
          )}
        </div>
      </div>
    </div>
  );
}
