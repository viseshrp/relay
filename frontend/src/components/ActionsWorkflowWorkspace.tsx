import type { WorkflowWorkspaceProps } from "./WorkflowWorkspace";

import { useActionsWorkflowWorkspace } from "./useActionsWorkflowWorkspace";
import { ActionsWorkflowWorkspaceView } from "./ActionsWorkflowWorkspaceView";
export function ActionsWorkflowWorkspace(props: WorkflowWorkspaceProps) {
  const state = useActionsWorkflowWorkspace(props);
  if (state.fallback !== null) return state.fallback;
  return <ActionsWorkflowWorkspaceView state={state} />;
}
