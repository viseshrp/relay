import { apiRequest } from "@/api/client";
import type { RunDetail, RunListResponse } from "@/types/api";

export function listRuns(params?: Record<string, string | number | undefined>) {
  const search = new URLSearchParams();
  Object.entries(params ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      search.set(key, String(value));
    }
  });
  return apiRequest<RunListResponse>(`/runs${search.toString() ? `?${search.toString()}` : ""}`);
}

export function createRun(payload: Record<string, unknown>) {
  return apiRequest<RunDetail>("/runs", { method: "POST", body: JSON.stringify(payload) });
}

export function getRun(runId: string) {
  return apiRequest<RunDetail>(`/runs/${runId}`);
}

export function deleteRun(runId: string) {
  return apiRequest<void>(`/runs/${runId}`, { method: "DELETE" });
}
