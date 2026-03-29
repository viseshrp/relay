export type WorkflowStatus =
  | "queued"
  | "running"
  | "waiting_for_user"
  | "completed"
  | "completed_with_unresolved_findings"
  | "failed"
  | "cancelled";

export type PhaseStatus =
  | "queued"
  | "starting"
  | "running"
  | "retrying"
  | "succeeded"
  | "failed"
  | "cancelled"
  | "stale"
  | "waiting_for_user";

export type PhaseType =
  | "exploration"
  | "planning"
  | "plan_critique"
  | "plan_correction"
  | "execution"
  | "review";

export type ReviewSeverity = "error" | "warning" | "suggestion";

export const KNOWN_MODELS = [
  { id: "", name: "Default (Copilot default)" },
  { id: "gpt-4o", name: "GPT-4o" },
  { id: "gpt-4.1", name: "GPT-4.1" },
  { id: "gpt-4.1-mini", name: "GPT-4.1 Mini" },
  { id: "gpt-4.1-nano", name: "GPT-4.1 Nano" },
  { id: "claude-sonnet-4", name: "Claude Sonnet 4" },
  { id: "claude-3.5-sonnet", name: "Claude 3.5 Sonnet" },
  { id: "gemini-2.0-flash", name: "Gemini 2.0 Flash" },
  { id: "o3-mini", name: "o3-mini" },
] as const;

export interface CopilotStatus {
  gh_available?: boolean;
  copilot_available?: boolean;
  authenticated?: boolean;
  gh_path?: string | null;
  message?: string;
}

export interface Project {
  id: string;
  name: string;
  path: string;
  is_git_repo: boolean;
  active_run_count: number;
  path_accessible: boolean;
  current_branch: string | null;
  created_at: string;
  updated_at: string;
}

export interface ProjectSettings {
  project_id: string;
  phase_model_mapping: Record<string, string>;
  retry_count: number | null;
  review_fix_loop_limit: number | null;
  autopilot_default: boolean | null;
}

export interface FileTreeNode {
  path: string;
  name: string;
  node_type: "file" | "directory";
  children: FileTreeNode[];
}

export interface AttemptSummary {
  attempt_number: number;
  status: string;
  started_at: string | null;
  ended_at: string | null;
}

export interface PhaseSummary {
  id: string;
  phase_type: PhaseType;
  sequence_number: number;
  status: PhaseStatus;
  current_attempt: number;
  latest_attempt: AttemptSummary | null;
}

export interface RunSummary {
  id: string;
  project_id: string;
  project_name: string;
  name: string;
  status: WorkflowStatus;
  branch: string | null;
  head_commit: string | null;
  autopilot: boolean;
  review_fix_loop_count: number;
  review_fix_loop_limit: number;
  retry_limit: number;
  context_paths: string[];
  created_at: string;
  updated_at: string;
}

export interface RunDetail extends RunSummary {
  phases: PhaseSummary[];
}

export interface RunListResponse {
  items: RunSummary[];
  total: number;
}

export interface ReviewComment {
  id: string;
  file_path: string | null;
  line_number: number | null;
  severity: ReviewSeverity;
  comment: string;
}

export interface AttemptDetail {
  id: string;
  phase_id: string;
  attempt_number: number;
  status: string;
  pid: number | null;
  exit_code: number | null;
  started_at: string | null;
  ended_at: string | null;
  error_message: string | null;
  log_file_path: string;
  rendered_prompt: string;
  review_comments: ReviewComment[];
}

export interface PhaseDetail {
  id: string;
  workflow_run_id: string;
  phase_type: PhaseType;
  sequence_number: number;
  status: PhaseStatus;
  current_attempt: number;
  attempts: AttemptDetail[];
}

export interface LogResponse {
  lines: string[];
  next_offset: number;
}

export interface PromptResponse {
  prompt: string;
}

export interface ExplorationMessage {
  id: string;
  workflow_run_id: string;
  role: "user" | "assistant";
  content: string;
  sequence_number: number;
  created_at: string;
}

export interface ExplorationContextResponse {
  run_id: string;
  context_paths: string[];
}

export interface UserSettings {
  relay_data_dir: string;
  copilot_cli_path_override: string | null;
  phase_model_mapping: Record<string, string>;
  autopilot: boolean;
  retry_limit: number;
  review_fix_loop_limit: number;
  theme: string;
}

export interface HealthResponse {
  ok: boolean;
  database: string;
  worker: string;
  copilot: CopilotStatus;
}

export interface SystemStatusResponse {
  version: string;
  worker_status: string;
  concurrency_limit: number;
  active_workflows: number;
  copilot: CopilotStatus;
}
