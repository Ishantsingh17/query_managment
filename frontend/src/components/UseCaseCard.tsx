import {
  CalendarDays,
  CheckCircle2,
  FileSearch,
  Landmark,
  TrendingDown,
} from "lucide-react";
import type { ComponentType } from "react";
import type { UseCase } from "@/lib/types";

const ICONS: Record<string, ComponentType<{ className?: string }>> = {
  "trending-down": TrendingDown,
  calendar: CalendarDays,
  landmark: Landmark,
  "file-search": FileSearch,
};

export function UseCaseCard({
  useCase,
  showEvidence = false,
}: {
  useCase: UseCase;
  showEvidence?: boolean;
}) {
  const Icon = ICONS[useCase.icon] ?? FileSearch;

  return (
    <article className="card flex flex-col p-6">
      <div className="flex items-start gap-4">
        <span className="flex h-11 w-11 shrink-0 items-center justify-center rounded-control bg-primary-soft">
          <Icon className="h-5 w-5 text-primary" aria-hidden="true" />
        </span>

        <div className="min-w-0 flex-1">
          <span className="inline-flex items-center gap-1 rounded-md bg-primary-soft px-2 py-0.5 text-[11px] font-semibold uppercase tracking-[0.04em] text-primary">
            <CheckCircle2 className="h-3 w-3" aria-hidden="true" />
            Supported
          </span>
          <h3 className="mt-1.5 text-[17px] font-semibold leading-snug text-ink">
            {useCase.short_name}
          </h3>
        </div>
      </div>

      <p className="mt-4 text-[14px] leading-relaxed text-ink-muted">
        {useCase.description}
      </p>

      <div className="mt-5">
        <p className="text-[13px] text-ink-muted">Required Inputs</p>
        <ul className="mt-2 flex flex-wrap gap-2">
          {useCase.required_parameter_labels.map((label) => (
            <li key={label} className="chip">
              {label}
            </li>
          ))}
        </ul>
      </div>

      {showEvidence && (
        <div className="mt-5 border-t border-line pt-4">
          <p className="text-[13px] text-ink-muted">
            Required Evidence ({useCase.required_evidence.length})
          </p>
          <ul className="mt-2 space-y-1.5">
            {useCase.required_evidence.map((item) => (
              <li
                key={item.code}
                className="flex items-start gap-2 text-[13px] text-ink-soft"
              >
                <span
                  className="mt-1.5 h-1.5 w-1.5 shrink-0 rounded-full bg-primary"
                  aria-hidden="true"
                />
                <span>
                  {item.label}
                  {item.human_required && (
                    <span className="ml-2 inline-flex items-center rounded bg-warning-soft px-1.5 py-0.5 text-[11px] font-semibold uppercase tracking-[0.04em] text-warning-text">
                      Human input
                    </span>
                  )}
                </span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </article>
  );
}
