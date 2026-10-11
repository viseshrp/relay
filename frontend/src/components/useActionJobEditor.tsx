import { useState } from "react";
import type { ActionWorkflow } from "../actions-workflow";
import type { AgentRecord, ProviderDefaults } from "../types";
import type { LanguageManifest } from "../workflow-language";
import { expressionSuggestions } from "../workflow-language";

import type { PromptEdits } from "./PromptFilesEditor";

export function useActionJobEditor({
  workflow,
  jobId,
  index,
  onIndex,
  manifest,
  change,
  onMove,
  agents,
  defaults,
  defaultModel,
  project,
  workflowKey,
  edits,
  onEdits,
}: {
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
  const [tab, setTab] = useState("General");
  const job = workflow.jobs[jobId];
  const step = job?.steps?.[index];
  if (!job) return null;
  const field = (key: string, value: unknown) =>
    change(["jobs", jobId, key], value);
  const stepField = (key: string, value: unknown) =>
    change(["jobs", jobId, "steps", index, key], value);
  const input = (key: string, value: unknown) =>
    change(
      key === "__all__"
        ? ["jobs", jobId, "steps", index, "with"]
        : ["jobs", jobId, "steps", index, "with", key],
      value,
    );
  const suggestions = expressionSuggestions(workflow, jobId);

  return {
    fallback: null as null,
    tab,
    setTab,
    job,
    field,
    workflow,
    jobId,
    suggestions,
    change,
    manifest,
    index,
    onIndex,
    step,
    stepField,
    agents,
    defaults,
    defaultModel,
    project,
    workflowKey,
    edits,
    onEdits,
    input,
    onMove,
  };
}
export type ActionJobEditorState = Extract<
  ReturnType<typeof useActionJobEditor>,
  { fallback: null }
>;
