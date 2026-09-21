import type {
  AuditRequestDetail,
  AuditRequestSummary,
  PackageView,
  ReviewActionType,
  UseCase,
} from "./types";

export const API_BASE_URL =
  process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export class ApiError extends Error {
  status: number;

  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      ...init,
      headers: {
        "Content-Type": "application/json",
        ...(init?.headers ?? {}),
      },
      cache: "no-store",
    });
  } catch {
    throw new ApiError(
      "Could not reach the backend. Confirm it is running on " + API_BASE_URL,
      0,
    );
  }

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`;
    try {
      const body = await response.json();
      if (typeof body?.detail === "string") detail = body.detail;
    } catch {
      /* keep the default message */
    }
    throw new ApiError(detail, response.status);
  }

  if (response.status === 204) return undefined as T;
  return (await response.json()) as T;
}

export const api = {
  getUseCases: () => request<UseCase[]>("/api/use-cases"),

  listRequests: () => request<AuditRequestSummary[]>("/api/audit-requests"),

  createRequest: (query: string) =>
    request<{ request_id: string; status: string }>("/api/audit-requests", {
      method: "POST",
      body: JSON.stringify({ query }),
    }),

  getRequest: (requestId: string) =>
    request<AuditRequestDetail>(`/api/audit-requests/${requestId}`),

  runRequest: (requestId: string) =>
    request<AuditRequestDetail>(`/api/audit-requests/${requestId}/run`, {
      method: "POST",
    }),

  retryRequest: (requestId: string) =>
    request<AuditRequestDetail>(`/api/audit-requests/${requestId}/retry`, {
      method: "POST",
    }),

  /** Answer a request that halted for missing mandatory inputs. */
  clarify: (requestId: string, answer: string) =>
    request<AuditRequestDetail>(`/api/audit-requests/${requestId}/clarify`, {
      method: "POST",
      body: JSON.stringify({ answer }),
    }),

  review: (
    requestId: string,
    action: ReviewActionType,
    comment?: string,
    reviewerName?: string,
  ) =>
    request<AuditRequestDetail>(`/api/audit-requests/${requestId}/review`, {
      method: "POST",
      body: JSON.stringify({
        action,
        comment: comment?.trim() ? comment.trim() : null,
        reviewer_name: reviewerName ?? "J. Al-Farsi",
      }),
    }),

  getPackage: (requestId: string) =>
    request<PackageView>(`/api/audit-requests/${requestId}/package`),

  /** Direct link used by the View actions; the browser opens it. */
  evidenceFileUrl: (requestId: string, evidenceId: string) =>
    `${API_BASE_URL}/api/audit-requests/${requestId}/evidence/${evidenceId}/file`,
};
