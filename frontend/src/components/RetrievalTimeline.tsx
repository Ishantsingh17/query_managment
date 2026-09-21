import { AlertTriangle, Check, Loader2 } from "lucide-react";
import type { TimelineStep } from "@/lib/types";

const NODE_STYLE: Record<string, string> = {
  COMPLETE: "border-success bg-success text-white",
  ACTIVE: "border-primary bg-primary text-white",
  ERROR: "border-danger bg-danger text-white",
  PENDING: "border-line bg-card text-ink-faint",
};

const LABEL_STYLE: Record<string, string> = {
  COMPLETE: "text-ink",
  ACTIVE: "text-primary font-semibold",
  ERROR: "text-danger-text font-semibold",
  PENDING: "text-ink-muted",
};

const DETAIL_STYLE: Record<string, string> = {
  COMPLETE: "text-success-text",
  ACTIVE: "text-primary",
  ERROR: "text-danger-text",
  PENDING: "text-ink-faint",
};

function Node({ status }: { status: string }) {
  return (
    <span
      className={`relative z-10 flex h-7 w-7 items-center justify-center rounded-full border-2 ${NODE_STYLE[status] ?? NODE_STYLE.PENDING}`}
    >
      {status === "COMPLETE" && <Check className="h-4 w-4" aria-hidden="true" />}
      {status === "ACTIVE" && (
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
      )}
      {status === "ERROR" && (
        <AlertTriangle className="h-3.5 w-3.5" aria-hidden="true" />
      )}
      {status === "PENDING" && (
        <span className="h-2 w-2 rounded-full bg-ink-faint" aria-hidden="true" />
      )}
    </span>
  );
}

export function RetrievalTimeline({ steps }: { steps: TimelineStep[] }) {
  return (
    <section className="card">
      <div className="card-header">
        <h2 className="card-title">Evidence Retrieval Progress</h2>
        <p className="card-subtitle">
          Sequential search across configured data sources
        </p>
      </div>

      {/* Scrolls horizontally on narrow viewports so the page body never does. */}
      <div className="overflow-x-auto px-6 py-8">
        {/* Steps share the width evenly and only start scrolling once they
            would fall below a readable minimum, so no step is ever clipped. */}
        <ol
          className="flex items-start"
          style={{ minWidth: `${steps.length * 84}px` }}
          aria-label="Retrieval progress"
        >
          {steps.map((step, index) => {
            const previous = steps[index - 1];
            return (
              <li
                key={step.key}
                className="relative flex min-w-0 flex-1 flex-col items-center px-1 text-center"
              >
                {/* Connector rails, drawn behind the node. */}
                {index > 0 && (
                  <span
                    aria-hidden="true"
                    className={`absolute left-0 top-[13px] h-0.5 w-1/2 ${
                      previous?.status === "COMPLETE" ? "bg-success" : "bg-line"
                    }`}
                  />
                )}
                {index < steps.length - 1 && (
                  <span
                    aria-hidden="true"
                    className={`absolute right-0 top-[13px] h-0.5 w-1/2 ${
                      step.status === "COMPLETE" ? "bg-success" : "bg-line"
                    }`}
                  />
                )}

                <Node status={step.status} />

                <span
                  className={`mt-3 text-[13px] leading-snug ${LABEL_STYLE[step.status] ?? LABEL_STYLE.PENDING}`}
                >
                  {step.label}
                </span>

                {step.detail && (
                  <span
                    className={`mt-1 text-meta ${DETAIL_STYLE[step.status] ?? DETAIL_STYLE.PENDING}`}
                  >
                    {step.detail}
                  </span>
                )}
                {step.sub_detail && (
                  <span
                    className={`mt-0.5 text-meta leading-snug ${DETAIL_STYLE[step.status] ?? DETAIL_STYLE.PENDING}`}
                  >
                    {step.sub_detail}
                  </span>
                )}
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}
