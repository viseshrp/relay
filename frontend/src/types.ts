export type JsonScalar = string | number | boolean | null;
export type JsonValue = JsonScalar | JsonValue[] | { [key: string]: JsonValue };

export interface ApiErrorBody {
  code: string;
  message: string;
  context: Record<string, JsonValue>;
  next_action?: string;
}

export interface AuthState {
  owner_created: boolean;
  authenticated: boolean;
  username: string | null;
  login_required: boolean;
  password_rules?: string[];
}

export interface WorkflowDraft {
  yaml: string;
  base_hash: string;
  validation_state: "valid" | "invalid" | "unchecked";
  updated_at: string;
}

export interface WorkflowDocumentResponse {
  yaml: string;
  draft: WorkflowDraft | null;
  base_hash: string;
  project: ProjectRecord;
  warnings: HandoffWarning[];
  repair_defaults: RepairDefaults;
}

export interface RepairDefaults {
  max_rounds: number;
  max_allowed_rounds: number;
  fix_instruction: string;
  verify_instruction: string;
}

export interface ProjectRecord {
  id: string;
  canonical_path: string;
  display_name: string;
  git_root: string;
}

export interface HandoffWarning {
  workflow_key?: string;
  scope_path: string;
  output: string;
  artifact: string;
  message: string;
}

export interface ModelObservation {
  value: string;
  name: string;
  config_id: string;
  agent_version: string;
  observed_at: string;
}

export interface AgentRecord {
  id: string;
  display_name: string;
  driver: "acp" | "antigravity";
  installed: boolean;
  detected_version: string | null;
  reason: string | null;
  install_url: string;
  models: ModelObservation[];
}

export interface AgentsResponse {
  agents: AgentRecord[];
  preferences: string[];
  registry: {
    source_url: string;
    fetched_at: string;
    cache_age_seconds: number;
    stale: boolean;
    warning: string | null;
  };
}

export interface AgentReadiness {
  id: string;
  display_name: string;
  install_url: string;
  installed: boolean;
  ready: boolean;
  error_code: string | null;
  reason: string | null;
  cleanup_warning: string | null;
  models: string[];
  login_command: string;
  login_guidance: string;
}

export interface WorkflowTemplate {
  id: string;
  name: string;
  description: string;
  jobs: string[];
  required_agents: string;
  inputs: Record<string, {
    type: string;
    description?: string | null;
    default?: JsonScalar;
    required: boolean;
    constraints?: { values?: string[] };
  }>;
}

export interface AgentOptions {
  effort?: string;
  permission_mode?: string;
}

export interface ConfigurationSelector {
  config_id: string;
  name: string;
  current_value: string;
  choices: Array<{ value: string; name: string; description: string | null }>;
  transport: "config_option" | "session_mode" | "native";
}

export interface AgentConfiguration {
  agent_id: string;
  model_value: string;
  effort: ConfigurationSelector | null;
  permission_mode: ConfigurationSelector | null;
}

export interface RetryOptions {
  agent_id?: string;
  model?: string;
  effort?: string | null;
  permission_mode?: string | null;
  handoff_prompt?: string;
}

export interface RunSummary {
  id: string;
  project_id: string;
  workflow_key: string;
  status: string;
  source_commit: string;
  run_branch: string;
  worktree_state: string;
  cleanup_policy: string;
  launcher: string;
  started_at: string | null;
  ended_at: string | null;
  failure_code: string | null;
  failure_summary: string | null;
  entry_point: string | null;
  dispatch_paused: boolean;
}

export interface RunNode {
  id: string;
  scope_path: string;
  node_id: string;
  node_type: string;
  status: string;
  writes: boolean;
  selected_branch: string | null;
  loop_index: number | null;
  parent_scope: string | null;
  dependencies: string[];
  controls: Array<{ target: string; label: string }>;
  repair_for?: string | null;
  repair_settings?: {
    legacy: boolean;
    max_rounds: number;
    accepted_output: string | null;
    accepted_value: JsonScalar;
    fix_instruction: string | null;
    verify_instruction: string | null;
    roles: Record<string, {
      type: string; model: string | null; agents: string[] | null;
      agent_options: Record<string, AgentOptions> | null; writes: boolean | null;
    }>;
  } | null;
  retry_settings?: RetryConfiguration | null;
  pending_settings?: RetryConfiguration | null;
}

export interface RunInteraction {
  id: string;
  attempt_id: string;
  scope_path: string;
  kind: "permission" | "elicitation" | "wait";
  request: Record<string, JsonValue>;
  response: Record<string, JsonValue> | null;
  status: string;
  deadline: string | null;
  created_at: string;
  answered_at: string | null;
}

export interface RunDetail extends RunSummary {
  problem: RunProblem | null;
  recovery: {
    enabled: boolean;
    max_retries: number;
    current: {
      scope_path: string;
      attempt_number: number;
      retry_number: number;
      state: "scheduled" | "preparing" | "resumed" | "blocked" | "exhausted" | "canceled";
      instruction: string;
      instruction_sha256: string;
      message: string;
    } | null;
  };
  event_cursor: number;
  project: ProjectRecord;
  snapshot: {
    relay_version: string;
    runtime_versions: Record<string, JsonValue>;
    hashes: Record<string, JsonValue>;
    created_at: string;
  };
  nodes: RunNode[];
  interactions: RunInteraction[];
}

export interface RetryConfiguration {
  scope_path: string;
  agent_id: string;
  model_value: string;
  effort?: string | null;
  permission_mode?: string | null;
  default_handoff_prompt?: string;
  handoff_prompt_max_bytes?: number;
}

export interface RunProblem extends RetryConfiguration {
  attempt_number: number;
  error_code: string | null;
  stop_reason: string | null;
  exit_code: number | null;
  message: string | null;
  provider_message: string | null;
  provider_message_truncated: boolean;
  retry?: {
    state: "scheduled" | "blocked" | "canceled" | "resumed";
    reset_at: string | null;
    error_message: string | null;
  } | null;
}

export interface RunEvent {
  id: number;
  type: string;
  version: number;
  source: string;
  ts: string;
  payload: Record<string, JsonValue>;
}

export interface ArtifactRecord {
  id: string;
  attempt_id: string;
  name: string;
  source_path: string;
  sha256: string;
  bytes: number;
  media_type: string;
  preservation_state: string;
}
