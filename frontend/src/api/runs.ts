import { apiRequest } from "@/api/client";
import type { PromptResponse, RunDetail, RunListResponse } from "@/types/api";

export function listRuns(params?: Record<string, string | number | string[] | undefined>) {
  const search = new URLSearchParams();
  Object.entries(params ?? {}).forEach(([key, value]) => {
    if (value !== undefined && value !== "") {
      search.set(key, Array.isArray(value) ? value.join(",") : String(value));
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

export function getReviewFixPrompt(runId: string) {
  return apiRequest<PromptResponse>(`/runs/${runId}/review/fix-prompt`);
}
