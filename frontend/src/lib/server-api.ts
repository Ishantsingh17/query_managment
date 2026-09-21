import { API_BASE_URL } from "./api";
import type { AuditRequestSummary, UseCase } from "./types";

/**
 * Server-side fetch helpers.
 *
 * Data that does not need client interactivity is fetched on the server so
 * the first paint already contains it, rather than arriving after a
 * client-side effect.
 */
async function serverFetch<T>(path: string): Promise<T | null> {
  try {
    const response = await fetch(`${API_BASE_URL}${path}`, {
      cache: "no-store",
    });
    if (!response.ok) return null;
    return (await response.json()) as T;
  } catch {
    // The backend may not be running yet; callers render a fallback.
    return null;
  }
}

export const serverApi = {
  getUseCases: () => serverFetch<UseCase[]>("/api/use-cases"),
  listRequests: () => serverFetch<AuditRequestSummary[]>("/api/audit-requests"),
};
