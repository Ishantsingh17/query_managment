"use client";

import { use, useEffect, useState } from "react";
import Link from "next/link";
import {
  ArrowLeft,
  CheckCircle2,
  Eye,
  ExternalLink,
  FileText,
  Inbox,
  Package,
  RefreshCw,
  Search,
  ShieldCheck,
} from "lucide-react";
import type { ComponentType } from "react";
import { EmptyState, ErrorBanner, LoadingState } from "@/components/ErrorBanner";
import { StatusBadge } from "@/components/StatusBadge";
import { api, ApiError, API_BASE_URL } from "@/lib/api";
import { formatDate, formatDateTime, formatTime, titleCase } from "@/lib/format";
import type { PackageView } from "@/lib/types";

const TRAIL_ICONS: Record<string, ComponentType<{ className?: string }>> = {
  request_received: Inbox,
  query_understood: Search,
  retrieval_started: Search,
  retry_performed: RefreshCw,
  validation_complete: ShieldCheck,
  sent_for_review: Eye,
  review_approve: CheckCircle2,
  review_reject: CheckCircle2,
  review_retry: RefreshCw,
};

export default function PackagePage({
  params,
}: {
  params: Promise<{ requestId: string }>;
}) {
  const { requestId } = use(params);
  const [pkg, setPkg] = useState<PackageView | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    api
      .getPackage(requestId)
      .then(setPkg)
      .catch((err: ApiError) => setError(err.message))
      .finally(() => setLoading(false));
  }, [requestId]);

  if (loading) {
    return (
      <div className="px-8 py-8">
        <LoadingState label="Loading package…" />
      </div>
    );
  }

  if (!pkg) {
    return (
      <div className="mx-auto max-w-detail px-8 py-8">
        {error ? (
          <ErrorBanner title="Package not available" message={error} tone="warning" />
        ) : (
          <EmptyState title="No package has been generated yet." />
        )}
        <div className="mt-6">
          <Link
            href={`/requests/${requestId}`}
            className="inline-flex items-center gap-1.5 text-[13px] text-ink-muted hover:text-primary"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Back to Request
          </Link>
        </div>
      </div>
    );
  }

  const summary = pkg.summary ?? {};
  const rows: Array<[string, string]> = [
    ["Request ID", pkg.request_id],
    ["Audit Requirement", summary.requirement_name ?? "—"],
    ["Use Case", summary.use_case_id ?? "—"],
  ];

  // Prefer the catalog's auditor-facing labels; fall back to the raw keys
  // only if an older package predates them.
  if (summary.parameters?.length) {
    for (const parameter of summary.parameters) {
      rows.push([parameter.label, parameter.value]);
    }
  } else {
    for (const [key, value] of Object.entries(summary.extracted_inputs ?? {})) {
      if (value === null || value === undefined || value === "") continue;
      const label = key
        .split("_")
        .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
        .join(" ");
      rows.push([label, Array.isArray(value) ? value.join(", ") : String(value)]);
    }
  }

  rows.push(
    [
      "Evidence Retrieved",
      `${summary.found_evidence?.length ?? 0} of ${summary.required_evidence?.length ?? 0} items`,
    ],
    ["Validation Result", summary.validation_status ? titleCase(summary.validation_status) : "—"],
    ["Retry Count", String(summary.retry_count ?? 0)],
    [
      "Reviewer Status",
      pkg.approved
        ? "Approved"
        : summary.reviewer_status
          ? titleCase(summary.reviewer_status)
          : "Pending",
    ],
  );

  if (pkg.approved_by) rows.push(["Approved By", `${pkg.approved_by} (AP Reviewer)`]);
  if (pkg.approved_at) rows.push(["Approved On", formatDateTime(pkg.approved_at)]);

  return (
    <div className="mx-auto max-w-detail px-8 py-8">
      {/* --- header ------------------------------------------------------ */}
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <Link
            href={`/requests/${requestId}`}
            className="inline-flex items-center gap-1.5 text-[13px] text-ink-muted hover:text-primary"
          >
            <ArrowLeft className="h-4 w-4" aria-hidden="true" />
            Back to Request
          </Link>

          <div className="mt-2 flex flex-wrap items-center gap-3">
            <h1 className="text-[28px] font-bold leading-tight tracking-[-0.01em] text-ink">
              Final Audit Evidence Package
            </h1>
            <span className="chip font-semibold">{pkg.request_id}</span>
            <StatusBadge status={pkg.status} size="lg" />
          </div>

          {pkg.approved ? (
            <p className="mt-1.5 text-[13px] text-ink-muted">
              Approved on {formatDate(pkg.approved_at)}
              {pkg.approved_by ? ` · AP Reviewer: ${pkg.approved_by}` : ""}
            </p>
          ) : (
            <p className="mt-1.5 text-[13px] text-ink-muted">{pkg.package_path}</p>
          )}
        </div>

        {/* Serves the whole package as a ZIP: the evidence directory plus the
            three JSON summaries. */}
        <a
          href={`${API_BASE_URL}/api/audit-requests/${pkg.request_id}/package/download`}
          className="btn-primary shrink-0"
          title={`Download ${pkg.request_id}_audit_evidence_package.zip`}
        >
          <Package className="h-4 w-4" aria-hidden="true" />
          Open Package
        </a>
      </div>

      {/* --- approval banner -------------------------------------------- */}
      {pkg.approved ? (
        <div className="mt-6 flex items-start gap-3 rounded-card border border-success-border bg-success-soft px-5 py-4">
          <CheckCircle2
            className="mt-0.5 h-5 w-5 shrink-0 text-success-text"
            aria-hidden="true"
          />
          <div>
            <p className="text-[15px] font-semibold text-success-text">
              Evidence package approved
            </p>
            <p className="mt-0.5 text-[13px] text-success-text">
              This package has been approved and is ready for audit use.
            </p>
          </div>
        </div>
      ) : (
        <div className="mt-6">
          <ErrorBanner
            title="Awaiting reviewer approval"
            message="This package has been generated but not yet approved."
            tone="info"
          />
        </div>
      )}

      <div className="mt-6 grid gap-6 lg:grid-cols-2">
        {/* --- package summary ----------------------------------------- */}
        <section className="card">
          <div className="card-header">
            <h2 className="card-title">Package Summary</h2>
          </div>
          <dl className="divide-y divide-line">
            {rows.map(([label, value], index) => (
              <div
                key={label}
                className={`flex items-start justify-between gap-6 px-6 py-3.5 ${
                  index % 2 === 1 ? "bg-canvas" : ""
                }`}
              >
                <dt className="text-[13px] text-ink-muted">{label}</dt>
                <dd className="text-right text-[13px] font-semibold text-ink">
                  {value}
                </dd>
              </div>
            ))}
          </dl>
        </section>

        {/* --- retrieval & review trail -------------------------------- */}
        <section className="card">
          <div className="card-header">
            <h2 className="card-title">Retrieval &amp; Review Trail</h2>
          </div>
          <ol className="p-6">
            {pkg.trail.map((entry, index) => {
              const Icon = TRAIL_ICONS[entry.key] ?? CheckCircle2;
              const last = index === pkg.trail.length - 1;
              return (
                <li key={`${entry.key}-${index}`} className="relative flex gap-4 pb-6 last:pb-0">
                  {!last && (
                    <span
                      aria-hidden="true"
                      className="absolute left-[15px] top-8 h-[calc(100%-2rem)] w-0.5 bg-line"
                    />
                  )}
                  <span className="relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-primary-soft">
                    <Icon className="h-4 w-4 text-primary" aria-hidden="true" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <div className="flex items-start justify-between gap-4">
                      <p className="text-[14px] font-semibold text-ink">
                        {entry.label}
                      </p>
                      <p className="shrink-0 text-[13px] text-ink-muted">
                        {formatTime(entry.timestamp)}
                      </p>
                    </div>
                    {entry.detail && (
                      <p className="mt-0.5 text-[13px] text-ink-muted">
                        {entry.detail}
                      </p>
                    )}
                  </div>
                </li>
              );
            })}
          </ol>
        </section>
      </div>

      {/* --- package contents ------------------------------------------- */}
      <section className="card mt-6">
        <div className="card-header">
          <h2 className="card-title">Package Contents</h2>
          <p className="card-subtitle">evidence/</p>
        </div>

        {pkg.contents.length === 0 ? (
          <EmptyState title="This package contains no evidence files." />
        ) : (
          <ul className="divide-y divide-line">
            {pkg.contents.map((file, index) => (
              <li
                key={file.filename || index}
                className={`flex flex-wrap items-center gap-4 px-6 py-4 ${
                  index % 2 === 1 ? "bg-canvas" : ""
                }`}
              >
                <FileText
                  className="h-5 w-5 shrink-0 text-primary"
                  aria-hidden="true"
                />
                <div className="min-w-0 flex-1">
                  <p className="truncate text-[14px] font-medium text-ink">
                    {file.filename}
                  </p>
                  <p className="mt-0.5 text-[13px] text-ink-muted">
                    {file.document_type_label} ·{" "}
                    {file.source_database_name || file.source_database_id}
                  </p>
                </div>
                <StatusBadge status={file.status} kind="evidence" size="sm" />
                {file.evidence_id ? (
                  <a
                    href={api.evidenceFileUrl(pkg.request_id, file.evidence_id)}
                    target="_blank"
                    rel="noreferrer"
                    className="inline-flex items-center gap-1.5 text-table font-semibold text-primary hover:underline"
                  >
                    <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                    View
                  </a>
                ) : (
                  <span className="text-table text-ink-faint">Unavailable</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      {summary.retry_note && (
        <p className="mt-6 flex items-start gap-2 rounded-control border border-line bg-card px-4 py-3 text-[13px] text-ink-muted">
          <RefreshCw className="mt-px h-4 w-4 shrink-0" aria-hidden="true" />
          {summary.retry_note}
        </p>
      )}
    </div>
  );
}
