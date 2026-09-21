import {
  AlertTriangle,
  Circle,
  Loader2,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import type { ComponentType } from "react";
import { StatusBadge } from "@/components/StatusBadge";
import type { EvidenceChecklistItem } from "@/lib/types";

const ROW_ICON: Record<string, ComponentType<{ className?: string }>> = {
  VALIDATED: ShieldCheck,
  FOUND: ShieldCheck,
  MISSING: AlertTriangle,
  SEARCHING: Loader2,
  PENDING: Circle,
};

const ICON_TONE: Record<string, string> = {
  VALIDATED: "text-success",
  FOUND: "text-primary",
  MISSING: "text-warning",
  SEARCHING: "text-primary animate-spin",
  PENDING: "text-ink-faint",
};

export function RequiredEvidenceChecklist({
  items,
  foundCount,
  requiredCount,
}: {
  items: EvidenceChecklistItem[];
  foundCount: number;
  requiredCount: number;
}) {
  const progress = requiredCount > 0 ? (foundCount / requiredCount) * 100 : 0;
  const complete = requiredCount > 0 && foundCount === requiredCount;

  return (
    <section className="card flex flex-col">
      <div className="card-header">
        <h2 className="card-title">Required Evidence</h2>
        <p className="card-subtitle">
          {requiredCount} items required for this use case
        </p>
      </div>

      <div className="flex flex-1 flex-col p-6">
        <div className="flex items-center gap-4">
          <p className="text-[13px] text-ink-muted">
            {foundCount} of {requiredCount} evidence items retrieved
          </p>
          <div
            className="h-1.5 flex-1 overflow-hidden rounded-full bg-chip"
            role="progressbar"
            aria-valuenow={foundCount}
            aria-valuemin={0}
            aria-valuemax={requiredCount}
            aria-label="Evidence retrieved"
          >
            <div
              className={`h-full rounded-full transition-all duration-500 ${
                complete ? "bg-success" : "bg-primary"
              }`}
              style={{ width: `${progress}%` }}
            />
          </div>
        </div>

        <ul className="mt-4 -mx-2">
          {items.map((item, index) => {
            const Icon = ROW_ICON[item.status] ?? Circle;
            return (
              <li
                key={item.code}
                className={`flex items-center gap-3 rounded-control px-2 py-2.5 ${
                  index % 2 === 1 ? "bg-canvas" : ""
                }`}
              >
                <Icon
                  className={`h-4 w-4 shrink-0 ${ICON_TONE[item.status] ?? "text-ink-faint"}`}
                  aria-hidden="true"
                />
                <span className="min-w-0 flex-1 truncate text-[14px] text-ink">
                  {item.label}
                </span>

                {item.generated && item.row_count !== null ? (
                  <span
                    className="shrink-0 text-table text-ink-muted"
                    title={item.identifier ?? undefined}
                  >
                    {item.row_count.toLocaleString()} rows
                  </span>
                ) : (
                  item.identifier && (
                    <span className="shrink-0 text-table text-ink-muted">
                      {item.identifier}
                    </span>
                  )
                )}
                {item.source_database_id && (
                  <span className="shrink-0 text-table text-ink-muted">
                    {item.source_database_name || item.source_database_id}
                  </span>
                )}
                {item.human_required && item.status === "MISSING" ? (
                  <span className="inline-flex shrink-0 items-center gap-1 rounded-md bg-warning-soft px-2 py-1 text-[11px] font-semibold uppercase tracking-[0.04em] text-warning-text">
                    <UserRound className="h-3 w-3" aria-hidden="true" />
                    Human input
                  </span>
                ) : (
                  <StatusBadge status={item.status} kind="evidence" size="sm" className="shrink-0" />
                )}
              </li>
            );
          })}
        </ul>
      </div>
    </section>
  );
}
