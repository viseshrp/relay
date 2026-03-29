import { apiRequest } from "@/api/client";
import type { AttemptDetail, LogResponse, PhaseDetail, PromptResponse } from "@/types/api";

export function listPhases(runId: string) {
  return apiRequest<PhaseDetail[]>(`/runs/${runId}/phases`);
}

export function getPhase(runId: string, phaseId: string) {
  return apiRequest<PhaseDetail>(`/runs/${runId}/phases/${phaseId}`);
}

export function getAttempt(runId: string, phaseId: string, attemptNumber: number) {
  return apiRequest<AttemptDetail>(`/runs/${runId}/phases/${phaseId}/attempts/${attemptNumber}`);
}

export function getLogs(runId: string, phaseId: string, attemptNumber: number, offset = 0) {
  return apiRequest<LogResponse>(`/runs/${runId}/phases/${phaseId}/attempts/${attemptNumber}/logs?offset=${offset}`);
}

export function getPrompt(runId: string, phaseId: string) {
  return apiRequest<PromptResponse>(`/runs/${runId}/phases/${phaseId}/prompt`);
}
