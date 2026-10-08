import type { ApiErrorBody, DashboardResponse, DashboardSection } from "./types";

export class RelayApiError extends Error {
  readonly status: number;
  readonly body: ApiErrorBody;

  constructor(status: number, body: ApiErrorBody) {
    super(body.message);
    this.name = "RelayApiError";
    this.status = status;
    this.body = body;
  }
}

function csrfToken(): string {
  // "other=1; relay_csrftoken=a%2Fb" -> "a/b"; a missing cookie -> "".
  const prefix = "relay_csrftoken=";
  const cookie = document.cookie
    .split(";")
    .map((part) => part.trim())
    .find((part) => part.startsWith(prefix));
  return cookie ? decodeURIComponent(cookie.slice(prefix.length)) : "";
}

function isErrorBody(value: unknown): value is ApiErrorBody {
  if (typeof value !== "object" || value === null) return false;
  const record = value as Record<string, unknown>;
  return typeof record.code === "string" && typeof record.message === "string";
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = init.method?.toUpperCase() ?? "GET";
  const headers = new Headers(init.headers);
  if (method !== "GET" && method !== "HEAD") {
    headers.set("Content-Type", "application/json");
    headers.set("X-CSRFToken", csrfToken());
  }
  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers,
  });
  if (!response.ok) {
    const value: unknown = await response.json().catch(() => null);
    const body: ApiErrorBody = isErrorBody(value)
      ? value
      : {
          code: "http_error",
          message: `Relay returned HTTP ${response.status}.`,
          context: {},
        };
    throw new RelayApiError(response.status, body);
  }
  return (await response.json()) as T;
}

export function errorMessage(error: unknown): string {
  if (error instanceof RelayApiError) {
    return error.body.next_action
      ? `${error.body.message} ${error.body.next_action}`
      : error.body.message;
  }
  return error instanceof Error ? error.message : "Relay could not complete the request.";
}

export function readDashboard(signal: AbortSignal, query: string, section?: DashboardSection, cursor?: string, limit = 10): Promise<DashboardResponse> {
  const parameters = new URLSearchParams({ limit: String(limit) });
  if (query) parameters.set("query", query);
  if (section) parameters.set("section", section);
  if (cursor) parameters.set("cursor", cursor);
  return api<DashboardResponse>(`/api/dashboard?${parameters}`, { signal });
}
