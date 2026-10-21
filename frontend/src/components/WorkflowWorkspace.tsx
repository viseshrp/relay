import { ActionsWorkflowWorkspace } from "./ActionsWorkflowWorkspace";

export interface WorkflowWorkspaceProps {
  initialCreate?: boolean;
  onRunLaunched: (runId: string) => void;
  project: import("../types").ProjectRecord;
  requestProject: string | null;
  initialWorkflow: string | null;
  initialLaunch: boolean;
  onLaunchClosed: () => void;
  onWorkflowLoaded: (key: string) => void;
  onNavigationReady: (callback: (() => Promise<void>) | null) => void;
  /** Open the Get started checklist, where agents are set up. */
  onOpenGetStarted?: () => void;
}

export function WorkflowWorkspace(props: WorkflowWorkspaceProps) {
  return <ActionsWorkflowWorkspace {...props} />;
}
