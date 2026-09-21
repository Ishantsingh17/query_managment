import { BrainCircuit, CheckCircle2, Info, AlertTriangle } from "lucide-react";
import { formatConfidence } from "@/lib/format";
import type { AuditRequestDetail } from "@/lib/types";

export function QueryUnderstandingCard({ detail }: { detail: AuditRequestDetail }) {
  const hasAmbiguities = detail.ambiguities.length > 0;

  return (
    <section className="card flex flex-col">
      <div className="card-header">
        <h2 className="card-title">What the System Understood</h2>
        <p className="card-subtitle">
          Structured interpretation of your audit requirement
        </p>
      </div>

      <div className="flex flex-1 flex-col p-6">
        <div className="flex items-start gap-4">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-control bg-primary-soft">
            <BrainCircuit className="h-5 w-5 text-primary" aria-hidden="true" />
          </span>

          <div className="min-w-0 flex-1">
            <p className="text-[13px] text-ink-muted">Classified Use Case</p>
            <p className="mt-0.5 text-[17px] font-semibold leading-snug text-ink">
              {detail.use_case_id
                ? `${detail.use_case_id} — ${detail.requirement_name ?? ""}`
                : "Not yet classified"}
            </p>
          </div>

          <div className="shrink-0 text-right">
            <p className="text-[13px] text-ink-muted">Confidence</p>
            <p className="text-[26px] font-bold leading-tight text-primary">
              {formatConfidence(detail.confidence)}
            </p>
          </div>
        </div>

        {detail.parse_source === "RULE_BASED" && (
          <p className="mt-4 flex items-start gap-2 rounded-control bg-primary-faint px-3 py-2 text-meta text-primary">
            <Info className="mt-px h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            Parsed by the deterministic rule-based parser (Groq not configured).
          </p>
        )}

        <hr className="my-6 border-line" />

        <p className="label-caps">Extracted Parameters</p>
        {detail.parameters.length > 0 ? (
          <dl className="mt-3 grid gap-3 sm:grid-cols-2">
            {detail.parameters.map((parameter) => (
              <div
                key={parameter.key}
                className="rounded-control border border-line bg-canvas px-4 py-3"
              >
                <dt className="text-meta text-ink-muted">{parameter.label}</dt>
                <dd className="mt-0.5 text-[15px] font-semibold text-ink">
                  {parameter.value}
                </dd>
              </div>
            ))}
          </dl>
        ) : (
          <p className="mt-3 text-[13px] text-ink-muted">
            No parameters were extracted from this request.
          </p>
        )}

        <hr className="my-6 border-line" />

        <p className="label-caps">Ambiguities</p>
        {hasAmbiguities ? (
          <ul className="mt-3 space-y-2">
            {detail.ambiguities.map((item) => (
              <li
                key={item}
                className="flex items-start gap-2 text-[13px] text-warning-text"
              >
                <AlertTriangle className="mt-px h-4 w-4 shrink-0" aria-hidden="true" />
                {item}
              </li>
            ))}
          </ul>
        ) : (
          <p className="mt-3 flex items-center gap-2 text-[14px] text-success-text">
            <CheckCircle2 className="h-4 w-4" aria-hidden="true" />
            None identified
          </p>
        )}
      </div>
    </section>
  );
}
