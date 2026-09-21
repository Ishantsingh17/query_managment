import { AuditRequestWorkspace } from "@/components/AuditRequestWorkspace";
import { serverApi } from "@/lib/server-api";

export default async function AuditRequestPage() {
  // Static catalog data, fetched on the server so the cards are in the first
  // paint rather than arriving after a client effect.
  const useCases = await serverApi.getUseCases();

  return (
    <>
      <header className="border-b border-line bg-card px-8 py-7">
        <h1 className="text-[28px] font-bold leading-tight tracking-[-0.01em] text-ink">
          Automated Audit Evidence Retrieval
        </h1>
        <p className="mt-1.5 text-[15px] text-ink-muted">
          Submit an audit requirement and track evidence retrieval.
        </p>
      </header>

      <AuditRequestWorkspace
        useCases={useCases ?? []}
        backendUnavailable={useCases === null}
      />
    </>
  );
}
