import { apiRequest } from "@/api/client";
import type { ExplorationContextResponse, ExplorationMessage } from "@/types/api";

export function listExplorationMessages(runId: string) {
  return apiRequest<ExplorationMessage[]>(`/runs/${runId}/exploration/messages`);
}

export function sendExplorationMessage(runId: string, content: string) {
  return apiRequest<ExplorationMessage>(`/runs/${runId}/exploration/messages`, {
    method: "POST",
    body: JSON.stringify({ content }),
  });
}

export function finalizeExploration(runId: string) {
  return apiRequest<{ run_id: string; finalize_requested: boolean }>(`/runs/${runId}/exploration/finalize`, {
    method: "POST",
  });
}

export function getExplorationContext(runId: string) {
  return apiRequest<ExplorationContextResponse>(`/runs/${runId}/exploration/context`);
}

export function updateExplorationContext(runId: string, contextPaths: string[]) {
  return apiRequest<ExplorationContextResponse>(`/runs/${runId}/exploration/context`, {
    method: "PUT",
    body: JSON.stringify({ context_paths: contextPaths }),
  });
}

export function advanceRun(runId: string) {
  return apiRequest(`/runs/${runId}/advance`, { method: "POST" });
}

export function rerunRun(runId: string, fromPhaseType: string) {
  return apiRequest(`/runs/${runId}/rerun`, { method: "POST", body: JSON.stringify({ from_phase_type: fromPhaseType }) });
}

export function approveReview(runId: string) {
  return apiRequest(`/runs/${runId}/review/approve`, { method: "POST" });
}

export function sendReviewFix(runId: string, fixPrompt?: string) {
  return apiRequest(`/runs/${runId}/review/fix`, {
    method: "POST",
    body: JSON.stringify({ fix_prompt: fixPrompt }),
  });
}

export function cancelRun(runId: string) {
  return apiRequest(`/runs/${runId}/cancel`, { method: "POST" });
}
