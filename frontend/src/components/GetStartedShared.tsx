import type { AgentReadiness, ProjectRecord } from "../types";

interface GetStartedProps {
  project: ProjectRecord;
  requestProject: string | null;
  runSucceeded: boolean;
  onWorkflowCreated: (key: string) => Promise<void>;
  onRunLaunched: (id: string) => void;
  onOpenProject: () => void;
  onClose: () => void;
}
function readinessLabel(
  row: AgentReadiness | undefined,
  installed: boolean,
  checking: boolean,
): string {
  if (!installed) return "Not installed";
  if (!row) return checking ? "Checking…" : "Check failed";
  if (row.ready) return "Ready to connect";
  return row.error_code === "agent_auth_error"
    ? "Sign in required"
    : "Check failed";
}
export { type GetStartedProps, readinessLabel };
