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

export interface ProjectLaunchSource {
  branch: string | null;
  commit: string | null;
}

export interface PreviousRunInputs {
  project_id: string;
  workflow_key: string;
  status: string;
  inputs: Record<string, JsonScalar>;
}

export interface LaunchCleanliness {
  clean: boolean;
  blocking_count: number;
  allowed_count: number;
  files: Array<{ status: string; path: string; original_path: string | null; allowed: boolean; reasons: string[] }>;
  truncated: boolean;
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
  defaults?: WorkflowDefaults;
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
  default?: boolean;
  inputs: Record<string, {
    type: string;
    description?: string | null;
    default?: JsonScalar;
    required: boolean;
    constraints?: { values?: string[] };
  }>;
}

export interface AgentOptions {
  effort?: string | null;
  permission_mode?: string | null;
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
  number: number;
  title: string;
  source_branch: string | null;
  created_at: string;
  project_id: string;
  workflow_key: string;
  status: string;
  source_commit: string;
  run_branch: string;
  worktree_state: string;
  cleanup_policy: string;
  merged_commit: string | null;
  launcher: string;
  started_at: string | null;
  ended_at: string | null;
  failure_code: string | null;
  failure_summary: string | null;
  entry_point: string | null;
  dispatch_paused: boolean;
  waiting_count?: number;
}

export interface DashboardProject extends ProjectRecord {
  unfinished_count: number;
  waiting_count: number;
  latest_run: RunSummary | null;
}

export interface DashboardRun extends RunSummary {
  project: ProjectRecord;
  request: { id: string; kind: string; scope_path: string } | null;
}

export interface DashboardPage<T> { items: T[]; next_cursor: string | null }
export interface DashboardData {
  counts: { projects: number; waiting: number; unfinished: number; paused: number };
  projects: DashboardPage<DashboardProject>;
  waiting: DashboardPage<DashboardRun>;
  active: DashboardPage<DashboardRun>;
  recent: DashboardPage<DashboardRun>;
}
export type DashboardSection = "projects" | "waiting" | "active" | "recent";
export type DashboardResponse = Pick<DashboardData, "counts"> & Partial<Omit<DashboardData, "counts">>;

export interface RunNode {
  display_name?: string;
  matrix?: Record<string, JsonValue>;
  outcome?: string;
  conclusion?: string;
  job_id?: string;
  step_id?: string;
  matrix_index?: number | null;
  id: string;
  scope_path: string;
  node_id: string;
  node_type: string;
  status: string;
  started_at?: string | null;
  ended_at?: string | null;
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

export interface JobAttempt {
  id: string;
  number: number;
  status: string;
  agent_id: string;
  model_value: string;
  started_at: string | null;
  ended_at: string | null;
  stop_reason: string | null;
  exit_code: number | null;
  error_code: string | null;
  error_message: string | null;
  provider_message: string | null;
  provider_message_truncated: boolean;
  starting_head: string;
  ending_head: string | null;
}

export interface RunJob {
  activity_type?: string;
  display_name?: string;
  working_folder: string;
  scope_path: string;
  node_type: string;
  status: string;
  writes: boolean;
  retry_settings: RetryConfiguration | null;
  command: string[] | null;
  prompt: string | null;
  instructions: Array<{ reference: { local?: string; global?: string }; text: string; truncated: boolean }>;
  outputs: Record<string, JsonValue>;
  attempts: JobAttempt[];
  latest_attempt: JobAttempt | null;
}

export interface JobChanges {
  text: string;
  truncated: boolean;
  source_commit: string;
  recorded_head: string;
  commits: Array<{ sha: string; title: string }>;
}

export interface RunInteraction {
  id: string;
  attempt_id: string;
  scope_path: string;
  kind: "permission" | "elicitation" | "wait";
  request: Record<string, JsonValue>;
  response: Record<string, JsonValue> | null;
  status: string;
  respondable?: boolean;
  deadline: string | null;
  created_at: string;
  answered_at: string | null;
}

export interface RunDetail extends RunSummary {
  working_folder: string;
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

export interface CapturedRunWorkflow {
  workflow_key: string;
  yaml: string;
  truncated: boolean;
  sha256: string;
}

export interface ArtifactRecord {
  scope_path: string;
  attempt_number: number;
  id: string;
  attempt_id: string;
  name: string;
  source_path: string;
  sha256: string;
  bytes: number;
  media_type: string;
  preservation_state: string;
}

export interface ProviderDefaults {
  model: string | null;
  effort?: string | null;
  permission_mode?: string | null;
}
export interface WorkflowDefaults {
  commands: Record<string, string[]>;
  env: Record<string, string>;
  model: string | null;
  providers: Record<string, ProviderDefaults>;
  timeout: string | null;
  auto_retry: boolean;
  recovery: { enabled: boolean; max_retries: number };
  repairs: { max_rounds: number; fix_instruction: string; verify_instruction: string };
}
export interface OwnerSettings {
  agent_preferences: string[];
  cleanup_policy: "clean_on_success" | "retain" | "merge_on_success";
  host: string;
  port: number;
  workers: number;
  login_required: boolean;
  workflow_defaults: WorkflowDefaults;
}
export interface SettingsResponse {
  settings: OwnerSettings;
  revision: string;
  active_login_required: boolean;
  username: string;
  paths: Record<"config" | "data" | "logs" | "prompts", string>;
}
export interface ProjectDefaultOverrides {
  agent_preferences?: string[];
  cleanup_policy?: OwnerSettings["cleanup_policy"];
  workflow_defaults?: Partial<Omit<WorkflowDefaults, "recovery" | "repairs">> & {
    recovery?: Partial<WorkflowDefaults["recovery"]>;
    repairs?: Partial<WorkflowDefaults["repairs"]>;
  };
}
export interface ProjectSettingsResponse {
  overrides: ProjectDefaultOverrides;
  revision: string;
  effective: OwnerSettings;
}
export interface StorageUsage {
  runs: number;
  artifacts: number;
  artifact_bytes: number;
  working_copies: { bytes: number; files: number; directories: number; truncated: boolean };
  branches: number;
  attempt_refs: number;
  cleanup_blocked: boolean;
}


export interface FolderListing {
  root: string;
  path: string;
  parent: string | null;
  folders: Array<{ name: string; path: string; repository: boolean }>;
  next: string | null;
}
