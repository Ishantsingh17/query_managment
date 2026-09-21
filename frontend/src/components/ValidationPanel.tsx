import {
  AlertTriangle,
  CheckCircle2,
  RefreshCw,
  ShieldCheck,
  UserRound,
  XCircle,
} from "lucide-react";
import { CheckResultLabel, StatusBadge } from "@/components/StatusBadge";
import type { Validation } from "@/lib/types";

const RESULT_ICON = {
  PASS: { Icon: CheckCircle2, tone: "text-success" },
  FAIL: { Icon: XCircle, tone: "text-danger" },
  REVIEW: { Icon: AlertTriangle, tone: "text-warning" },
} as const;

const BANNER = {
  COMPLETE: {
    wrapper: "border-success-border bg-success-soft",
    text: "text-success-text",
    Icon: ShieldCheck,
  },
  INCOMPLETE: {
    wrapper: "border-warning-border bg-warning-soft",
    text: "text-warning-text",
    Icon: AlertTriangle,
  },
  NEEDS_REVIEW: {
    wrapper: "border-warning-border bg-warning-soft",
    text: "text-warning-text",
    Icon: UserRound,
  },
  ERROR: {
    wrapper: "border-danger-border bg-danger-soft",
    text: "text-danger-text",
    Icon: XCircle,
  },
} as const;

export function ValidationPanel({
  validation,
  retryCount,
  retryNote,
  missingEvidence,
  showHeader = true,
}: {
  validation: Validation;
  retryCount?: number;
  retryNote?: string | null;
  missingEvidence?: string[];
  showHeader?: boolean;
}) {
  const banner =
    BANNER[validation.validation_status as keyof typeof BANNER] ?? BANNER.ERROR;

  return (
    <section className="card">
      {showHeader && (
        <div className="card-header">
          <h2 className="card-title">Validation</h2>
          <p className="card-subtitle">
            Deterministic checks against required evidence criteria
          </p>
        </div>
      )}

      <div className="p-6">
        <div className="flex items-center justify-between gap-4">
          <h3 className="text-[15px] font-semibold text-ink">Validation Checks</h3>
          <StatusBadge
            status={validation.validation_status}
            kind="validation"
            size="md"
          />
        </div>

        <ul className="mt-4 divide-y divide-line border-t border-line">
          {validation.checks.map((check) => {
            const { Icon, tone } = RESULT_ICON[check.result] ?? RESULT_ICON.REVIEW;
            return (
              <li
                key={`${check.code}-${check.label}`}
                className="flex items-start gap-3 py-3.5"
              >
                <Icon className={`mt-0.5 h-4 w-4 shrink-0 ${tone}`} aria-hidden="true" />
                <span className="min-w-0 flex-1">
                  <span className="block text-[14px] text-ink">{check.label}</span>
                  {check.detail && (
                    <span className="mt-0.5 block text-meta text-ink-muted">
                      {check.detail}
                    </span>
                  )}
                </span>
                <CheckResultLabel result={check.result} />
              </li>
            );
          })}
        </ul>

        {missingEvidence && missingEvidence.length > 0 && (
          <div className="mt-5 rounded-control border border-warning-border bg-warning-soft px-4 py-3">
            <p className="flex items-center gap-2 text-[13px] font-semibold text-warning-text">
              <AlertTriangle className="h-4 w-4" aria-hidden="true" />
              Missing evidence
            </p>
            <ul className="mt-1.5 list-inside list-disc text-[13px] text-warning-text">
              {missingEvidence.map((item) => (
                <li key={item}>{item}</li>
              ))}
            </ul>
          </div>
        )}

        {retryNote && (
          <p className="mt-5 flex items-start gap-2 rounded-control bg-canvas px-4 py-3 text-[13px] text-ink-muted">
            <RefreshCw className="mt-px h-4 w-4 shrink-0" aria-hidden="true" />
            {retryNote}
          </p>
        )}

        {!retryNote && retryCount === 0 && (
          <p className="mt-5 text-meta text-ink-muted">
            No retries were required.
          </p>
        )}

        <div
          className={`mt-5 flex items-start gap-3 rounded-control border px-4 py-3.5 ${banner.wrapper}`}
        >
          <banner.Icon
            className={`mt-0.5 h-5 w-5 shrink-0 ${banner.text}`}
            aria-hidden="true"
          />
          <div className="min-w-0">
            <p className={`text-[14px] font-semibold ${banner.text}`}>
              {validation.headline}
            </p>
            <p className={`mt-0.5 text-[13px] leading-relaxed ${banner.text}`}>
              {validation.message}
            </p>
          </div>
        </div>
      </div>
    </section>
  );
}
