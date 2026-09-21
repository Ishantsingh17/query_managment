"use client";

import { use } from "react";
import Link from "next/link";
import { ArrowLeft, Eye, Package, RefreshCw } from "lucide-react";
import { ClarificationPanel } from "@/components/ClarificationPanel";
import { EmptyState, ErrorBanner, LoadingState } from "@/components/ErrorBanner";
import { EvidenceTable } from "@/components/EvidenceTable";
import { QueryUnderstandingCard } from "@/components/QueryUnderstandingCard";
import { RequiredEvidenceChecklist } from "@/components/RequiredEvidenceChecklist";
import { RetrievalTimeline } from "@/components/RetrievalTimeline";
import { StatusBadge } from "@/components/StatusBadge";
import { ValidationPanel } from "@/components/ValidationPanel";
import { formatDateTime } from "@/lib/format";
import { useRequestPolling } from "@/lib/useRequestPolling";

const UNSUPPORTED_MESSAGE =
  "This POC supports four audit requirements: Cost Drill, Schedules, Trade Payables Balance Confirmation Samples, and Balance Confirmation Alternate Testing.";

export default function RequestDetailPage({
  params,
}: {
  params: Promise<{ requestId: string }>;
}) {
  const { requestId } = use(params);
  const { detail, error, loading, refresh } = useRequestPolling(requestId);

  if (loading && !detail) {
    return (
      <div className="px-8 py-8">
        <LoadingState label="Loading request…" />
      </div>
    );
  }

  if (error && !detail) {
    return (
      <div className="mx-auto max-w-detail px-8 py-8">
        <ErrorBanner title="Could not load this request" message={error} />
      </div>
    );
  }

  if (!detail) {
    return (
      <div className="px-8 py-8">
        <EmptyState title="Request not found" />
      </div>
    );
  }

  const readyForReview =
    detail.package_available &&
    ["READY_FOR_REVIEW", "INCOMPLETE"].includes(detail.status);
  const approved = detail.status === "APPROVED";
  const needsInput = detail.status === "NEEDS_INPUT";

  return (
    <div className="mx-auto max-w-detail px-8 py-8">
      {/* --- header ------------------------------------------------------ */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <Link
            href="/requests"
            className="inline-flex items-center gap-1.5 text-[13px] text-ink-muted hover:text-primary"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            All Requests
          </Link>

          <div className="mt-2 flex flex-wrap items-center gap-3">
            <h1 className="text-[28px] font-bold leading-tight tracking-[-0.01em] text-ink">
              Audit Request
            </h1>
            <span className="chip font-semibold">{detail.request_id}</span>
            <StatusBadge status={detail.status} size="lg" />
          </div>

          <p className="mt-1.5 text-[13px] text-ink-muted">
            Submitted · {formatDateTime(detail.created_at)}
          </p>
        </div>

        <div className="flex shrink-0 gap-3">
          {approved && (
            <Link href={`/requests/${requestId}/package`} className="btn-primary">
              <Package className="h-4 w-4" aria-hidden="true" />
              Open Package
            </Link>
          )}
          {readyForReview && !approved && (
            <Link href={`/requests/${requestId}/review`} className="btn-primary">
              <Eye className="h-4 w-4" aria-hidden="true" />
              Review Package
            </Link>
          )}
          {detail.is_active && (
            <span className="inline-flex items-center gap-2 rounded-control border border-line bg-card px-4 py-2.5 text-sm font-medium text-ink-muted">
              <RefreshCw className="h-4 w-4 animate-spin" aria-hidden="true" />
              Working…
            </span>
          )}
        </div>
      </div>

      {/* --- errors ------------------------------------------------------ */}
      {detail.status === "UNSUPPORTED" && (
        <div className="mt-6">
          <ErrorBanner
            title="This request is not supported"
            message={UNSUPPORTED_MESSAGE}
            tone="warning"
          />
        </div>
      )}
      {detail.status === "ERROR" && (
        <div className="mt-6">
          <ErrorBanner
            title="The request could not be understood confidently"
            message={
              detail.error_message ??
              "Please rephrase or provide the required identifiers."
            }
          />
        </div>
      )}

      {/* --- original query --------------------------------------------- */}
      <section className="card mt-6 p-6">
        <p className="label-caps">Original Query</p>
        <p className="mt-2.5 text-[15px] leading-relaxed text-ink">
          &ldquo;{detail.raw_query}&rdquo;
        </p>
      </section>

      {/* --- clarifying turn -------------------------------------------- */}
      {needsInput && (
        <div className="mt-6">
          <ClarificationPanel detail={detail} onAnswered={refresh} />
        </div>
      )}

      {/* --- understanding + checklist ---------------------------------- */}
      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        <QueryUnderstandingCard detail={detail} />
        {detail.required_evidence.length > 0 ? (
          <RequiredEvidenceChecklist
            items={detail.required_evidence}
            foundCount={detail.evidence_found_count}
            requiredCount={detail.evidence_required_count}
          />
        ) : (
          <section className="card">
            <div className="card-header">
              <h2 className="card-title">Required Evidence</h2>
              <p className="card-subtitle">Awaiting classification</p>
            </div>
            <EmptyState
              title="No requirements identified yet."
              message="The evidence checklist loads once the request is classified."
            />
          </section>
        )}
      </div>

      {/* --- progress ---------------------------------------------------- */}
      {detail.timeline.length > 0 && (
        <div className="mt-6">
          <RetrievalTimeline steps={detail.timeline} />
        </div>
      )}

      {/* --- retry note -------------------------------------------------- */}
      {detail.retry_note && (
        <p className="mt-6 flex items-start gap-2 rounded-card border border-line bg-card px-5 py-4 text-[13px] text-ink-muted shadow-card">
          <RefreshCw className="mt-px h-4 w-4 shrink-0" aria-hidden="true" />
          {detail.retry_note}
        </p>
      )}

      {/* --- retrieved evidence ----------------------------------------- */}
      {(detail.retrieved_evidence.length > 0 || detail.use_case_id) && (
        <div className="mt-6">
          <EvidenceTable
            requestId={requestId}
            rows={detail.retrieved_evidence}
            validated={detail.validation?.validation_status === "COMPLETE"}
          />
        </div>
      )}

      {/* --- validation -------------------------------------------------- */}
      {detail.validation && (
        <div className="mt-6">
          <ValidationPanel
            validation={detail.validation}
            retryCount={detail.retry_count}
            retryNote={null}
            missingEvidence={detail.missing_evidence}
          />
        </div>
      )}

      {/* --- review call to action -------------------------------------- */}
      {readyForReview && !approved && (
        <section className="card mt-6 flex flex-wrap items-center justify-between gap-4 p-6">
          <div>
            <h2 className="card-title">Review</h2>
            <p className="card-subtitle">
              The evidence package is ready for the AP reviewer.
            </p>
          </div>
          <Link href={`/requests/${requestId}/review`} className="btn-primary">
            <Eye className="h-4 w-4" aria-hidden="true" />
            Review Package
          </Link>
        </section>
      )}
    </div>
  );
}
