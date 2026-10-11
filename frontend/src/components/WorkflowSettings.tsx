import { useWorkflowSettings } from "./useWorkflowSettings";
import { WorkflowSettingsView } from "./WorkflowSettingsView";
export function WorkflowSettings(props: {
  open: boolean;
  projectId: string | null;
  yaml: string;
  onClose: () => void;
  onEnvironments: (names: string[]) => void;
}) {
  const state = useWorkflowSettings(props);
  if (state.fallback !== null) return state.fallback;
  return <WorkflowSettingsView state={state} />;
}
