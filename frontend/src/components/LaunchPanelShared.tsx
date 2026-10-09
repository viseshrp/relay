import type { PreviousRunInputs, ProjectRecord } from "../types";
import type { WorkflowValue } from "../workflow";

interface LaunchPanelProps {
  open: boolean;
  workflowKey: string | null;
  workflow: WorkflowValue | null;
  project: ProjectRecord;
  requestProject: string | null;
  modelOptions: string[];
  blockedReason: string | null;
  saveError: string | null;
  onSave?: () => void;
  onClose: () => void;
  onExited: () => void;
  onRunLaunched: (runId: string) => void;
  previousRun: PreviousRunInputs | null;
  draftNotice?: string | null;
  initialEntryPoint?: string;
}
export { type LaunchPanelProps };
