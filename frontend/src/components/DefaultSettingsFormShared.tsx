import type {
  AgentRecord,
  OwnerSettings,
  ProjectDefaultOverrides,
  WorkflowDefaults,
} from "../types";

interface Props {
  settings: OwnerSettings;
  agents: AgentRecord[];
  onChange: (settings: OwnerSettings) => void;
  project: string | null;
  disabled: boolean;
  overrides?: ProjectDefaultOverrides;
  onOverrides?: (values: ProjectDefaultOverrides) => void;
  tourActive?: boolean;
}
const overrideLabels: Record<
  keyof WorkflowDefaults | "agent_preferences" | "cleanup_policy",
  string
> = {
  agent_preferences: "agent order",
  cleanup_policy: "working-copy cleanup",
  model: "shared model",
  providers: "agent models and thinking",
  timeout: "job timeout",
  auto_retry: "automatic job retries",
  recovery: "automatic recovery",
  repairs: "new repair rules",
  commands: "shared commands",
  env: "environment variables",
};
export { type Props, overrideLabels };
