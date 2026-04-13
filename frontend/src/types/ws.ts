import type { PhaseType, WorkflowStatus } from "@/types/api";

export interface WorkflowStatusEvent {
  type: "workflow_status";
  run_id: string;
  status: WorkflowStatus;
  timestamp: string;
}

export interface PhaseStatusEvent {
  type: "phase_status";
  run_id: string;
  phase_id: string;
  phase_type: PhaseType;
  status: string;
  attempt_number: number;
  timestamp: string;
}

export interface LogEvent {
  type: "log";
  run_id: string;
  phase_id: string;
  attempt_number: number;
  stream: string;
  line: string;
  timestamp: string;
}

export interface ExplorationChunkEvent {
  type: "exploration_chunk";
  run_id: string;
  message_id: string;
  content: string;
  done: boolean;
}

export interface ExplorationFinalizedEvent {
  type: "exploration_finalized";
  run_id: string;
  planning_prompt_preview: string;
}

export interface ReviewResultsEvent {
  type: "review_results";
  run_id: string;
  phase_id: string;
  attempt_number: number;
  verdict: string;
  comment_count: number;
  summary_preview: string;
}

export interface ErrorEvent {
  type: "error";
  run_id: string;
  message: string;
  phase_type: string;
  timestamp: string;
}

export type RelayWsEvent =
  | WorkflowStatusEvent
  | PhaseStatusEvent
  | LogEvent
  | ExplorationChunkEvent
  | ExplorationFinalizedEvent
  | ReviewResultsEvent
  | ErrorEvent;
