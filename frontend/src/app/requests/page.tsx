import Link from "next/link";
import { ArrowRight, FilePlus2 } from "lucide-react";
import { EmptyState, ErrorBanner } from "@/components/ErrorBanner";
import { StatusBadge } from "@/components/StatusBadge";
import { formatDateTime } from "@/lib/format";
import { serverApi } from "@/lib/server-api";

export const dynamic = "force-dynamic";

export default async function RequestsPage() {
  const requests = await serverApi.listRequests();

  return (
    <>
      <header className="border-b border-line bg-card px-8 py-7">
        <h1 className="text-[28px] font-bold leading-tight tracking-[-0.01em] text-ink">
          Audit Requests
        </h1>
        <p className="mt-1.5 text-[15px] text-ink-muted">
          Every request submitted to this POC, newest first.
        </p>
      </header>

      <div className="mx-auto max-w-detail px-8 py-8">
        {requests === null && (
          <ErrorBanner
            title="Backend not reachable"
            message="Start the API with: uvicorn app.main:app --port 8000"
            tone="warning"
          />
        )}

        {requests !== null && requests.length === 0 && (
          <section className="card">
            <EmptyState
              title="No audit requests yet."
              message="Start by entering an audit requirement."
              action={
                <Link href="/audit" className="btn-primary">
                  <FilePlus2 className="h-4 w-4" aria-hidden="true" />
                  New Audit Request
                </Link>
              }
            />
          </section>
        )}

        {requests !== null && requests.length > 0 && (
          <section className="card">
            <div className="card-header flex flex-wrap items-center justify-between gap-4">
              <div>
                <h2 className="card-title">All Requests</h2>
                <p className="card-subtitle">
                  {requests.length}{" "}
                  {requests.length === 1 ? "request" : "requests"}
                </p>
              </div>
              <Link href="/audit" className="btn-primary">
                <FilePlus2 className="h-4 w-4" aria-hidden="true" />
                New Audit Request
              </Link>
            </div>

            <div className="overflow-x-auto">
              <table className="w-full min-w-[860px] border-collapse">
                <thead>
                  <tr className="border-b border-line bg-canvas">
                    <th scope="col" className="table-head">Request ID</th>
                    <th scope="col" className="table-head">Query</th>
                    <th scope="col" className="table-head">Use Case</th>
                    <th scope="col" className="table-head">Evidence</th>
                    <th scope="col" className="table-head">Status</th>
                    <th scope="col" className="table-head">Submitted</th>
                    <th scope="col" className="table-head" />
                  </tr>
                </thead>
                <tbody>
                  {requests.map((request, index) => (
                    <tr
                      key={request.request_id}
                      className={index % 2 === 1 ? "bg-canvas" : ""}
                    >
                      <td className="table-cell font-semibold text-ink">
                        {request.request_id}
                      </td>
                      <td className="table-cell max-w-[320px]">
                        <span className="line-clamp-2 text-ink-soft">
                          {request.raw_query}
                        </span>
                      </td>
                      <td className="table-cell">
                        {request.use_case_id ? (
                          <span className="block">
                            <span className="font-medium text-ink">
                              {request.use_case_id}
                            </span>
                            <span className="mt-0.5 block text-meta text-ink-muted">
                              {request.requirement_name}
                            </span>
                          </span>
                        ) : (
                          <span className="text-ink-faint">—</span>
                        )}
                      </td>
                      <td className="table-cell">
                        {request.evidence_required > 0 ? (
                          <span
                            className={
                              request.evidence_found === request.evidence_required
                                ? "font-semibold text-success-text"
                                : "text-ink-soft"
                            }
                          >
                            {request.evidence_found} / {request.evidence_required}
                          </span>
                        ) : (
                          <span className="text-ink-faint">—</span>
                        )}
                      </td>
                      <td className="table-cell">
                        <StatusBadge status={request.status} size="sm" />
                      </td>
                      <td className="table-cell whitespace-nowrap text-ink-muted">
                        {formatDateTime(request.created_at)}
                      </td>
                      <td className="table-cell">
                        <Link
                          href={`/requests/${request.request_id}`}
                          className="inline-flex items-center gap-1.5 font-semibold text-primary hover:underline"
                        >
                          Open
                          <ArrowRight className="h-3.5 w-3.5" aria-hidden="true" />
                        </Link>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )}
      </div>
    </>
  );
}
