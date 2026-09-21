import { ExternalLink, FileText, Table2 } from "lucide-react";
import { EmptyState } from "@/components/ErrorBanner";
import { StatusBadge } from "@/components/StatusBadge";
import { api } from "@/lib/api";
import { pluralise } from "@/lib/format";
import type { EvidenceRow } from "@/lib/types";

export function EvidenceTable({
  requestId,
  rows,
  validated,
}: {
  requestId: string;
  rows: EvidenceRow[];
  validated: boolean;
}) {
  return (
    <section className="card">
      <div className="card-header">
        <h2 className="card-title">Retrieved Evidence</h2>
        <p className="card-subtitle">
          {rows.length === 0
            ? "No evidence retrieved yet."
            : `${pluralise(rows.length, "document")} retrieved${validated ? " and validated" : ""}`}
        </p>
      </div>

      {rows.length === 0 ? (
        <EmptyState
          title="No evidence retrieved yet."
          message="Documents will appear here as each source is searched."
        />
      ) : (
        /* Table scrolls inside its own container; the page never scrolls sideways. */
        <div className="overflow-x-auto">
          <table className="w-full min-w-[720px] border-collapse">
            <thead>
              <tr className="border-b border-line bg-canvas">
                <th scope="col" className="table-head">Document Type</th>
                <th scope="col" className="table-head">Identifier</th>
                <th scope="col" className="table-head">Source DB</th>
                <th scope="col" className="table-head">Status</th>
                <th scope="col" className="table-head">Action</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row, index) => (
                <tr
                  key={row.evidence_id}
                  className={index % 2 === 1 ? "bg-canvas" : ""}
                >
                  <td className="table-cell">
                    <span className="flex items-center gap-2.5 font-medium text-ink">
                      {row.generated ? (
                        <Table2
                          className="h-4 w-4 shrink-0 text-success"
                          aria-hidden="true"
                        />
                      ) : (
                        <FileText
                          className="h-4 w-4 shrink-0 text-ink-muted"
                          aria-hidden="true"
                        />
                      )}
                      {row.document_type_label}
                    </span>
                  </td>
                  <td className="table-cell">
                    {/* A compiled extract's scope identifier is long and not
                        what a reader needs; the row count is. */}
                    {row.generated && row.row_count !== null ? (
                      <span className="chip" title={row.identifier ?? undefined}>
                        {row.row_count.toLocaleString()} rows
                      </span>
                    ) : row.identifier ? (
                      <span className="chip">{row.identifier}</span>
                    ) : (
                      <span className="text-ink-faint">—</span>
                    )}
                  </td>
                  <td className="table-cell">
                    {row.source_database_name || row.source_database_id}
                  </td>
                  <td className="table-cell">
                    <StatusBadge status={row.status} kind="evidence" size="sm" />
                  </td>
                  <td className="table-cell">
                    {row.has_file ? (
                      <a
                        href={api.evidenceFileUrl(requestId, row.evidence_id)}
                        target="_blank"
                        rel="noreferrer"
                        className="inline-flex items-center gap-1.5 font-semibold text-primary hover:underline"
                      >
                        <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" />
                        View
                      </a>
                    ) : (
                      <span className="text-ink-faint">Unavailable</span>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}
