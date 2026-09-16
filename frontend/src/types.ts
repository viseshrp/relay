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
  registry: {
    source_url: string;
    fetched_at: string;
    cache_age_seconds: number;
    stale: boolean;
    warning: string | null;
  };
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
}

export interface RunNode {
  id: string;
  scope_path: string;
  node_id: string;
  node_type: string;
  status: string;
  writes: boolean;
  outputs: Record<string, JsonValue>;
  selected_branch: string | null;
  loop_index: number | null;
}

export interface RunAttempt {
  id: string;
  node_run_id: string;
  scope_path: string;
  attempt_number: number;
  status: string;
  driver_kind: string | null;
  agent_id: string;
  agent_version: string;
  model_value: string;
  starting_head: string;
  ending_head: string | null;
  started_at: string | null;
  ended_at: string | null;
  stop_reason: string | null;
  exit_code: number | null;
  error_code: string | null;
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
  snapshot: {
    relay_version: string;
    runtime_versions: Record<string, JsonValue>;
    hashes: Record<string, JsonValue>;
    route_table: Record<string, JsonValue>;
    created_at: string;
  };
  nodes: RunNode[];
  attempts: RunAttempt[];
  interactions: RunInteraction[];
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
