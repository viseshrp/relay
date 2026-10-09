import type { ActionWorkflow } from "../actions-workflow";
import type { AgentRecord, ProviderDefaults } from "../types";
import type { LanguageManifest } from "../workflow-language";

import type { PromptEdits } from "./PromptFilesEditor";

import { useActionJobEditor } from "./useActionJobEditor";
import { ActionJobEditorView } from "./ActionJobEditorView";
export function ActionJobEditor(props: {
  workflow: ActionWorkflow;
  jobId: string;
  index: number;
  onIndex: (index: number) => void;
  manifest: LanguageManifest;
  change: (path: Array<string | number>, value: unknown) => void;
  onMove: (from: number, to: number) => void;
  agents: AgentRecord[];
  defaults: Record<string, ProviderDefaults>;
  defaultModel: string;
  project: string | null;
  workflowKey: string;
  edits: PromptEdits;
  onEdits: (reference: string, edit: PromptEdits[string]) => void;
}) {
  const state = useActionJobEditor(props);
  if (!state) return null;
  if (state.fallback !== null) return state.fallback;
  return <ActionJobEditorView state={state} />;
}
