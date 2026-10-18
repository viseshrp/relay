import { useState } from "react";
import type { ActionWorkflow } from "../actions-workflow";
import type { AgentRecord, ProviderDefaults } from "../types";
import type { LanguageManifest } from "../workflow-language";
import { fieldExpressions } from "../workflow-language";

import type { LoopTarget } from "./LoopWorkflowDialog";
import type { PromptEdits } from "./PromptFilesEditor";

export interface ActionJobEditorProps {
  workflow: ActionWorkflow;
  jobId: string;
  index: number;
  onIndex: (index: number) => void;
  manifest: LanguageManifest;
  change: (path: Array<string | number>, value: unknown) => void;
  onMove: (from: number, to: number) => void;
  agents: AgentRecord[];
  /** The saved agent order from Settings. */
  preferences: string[];
  defaults: Record<string, ProviderDefaults>;
  defaultModel: string;
  project: string | null;
  workflowKey: string;
  edits: PromptEdits;
  onEdits: (reference: string, edit: PromptEdits[string]) => void;
  /** The tab the drawer opens on. */
  initialTab: "General" | "Steps";
  /** The project's other workflows, which a loop step can repeat. */
  loopTargets: LoopTarget[];
  onRename: (id: string) => void;
  onEditYaml: () => void;
  onOpenGetStarted?: () => void;
}

export function useActionJobEditor({
  workflow,
  jobId,
  index,
  onIndex,
  manifest,
  change,
  onMove,
  agents,
  preferences,
  defaults,
  defaultModel,
  project,
  workflowKey,
  edits,
  onEdits,
  initialTab,
  loopTargets,
  onRename,
  onEditYaml,
  onOpenGetStarted,
}: ActionJobEditorProps) {
  const [tab, setTab] = useState<string>(initialTab);
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
  // Offer only what the server accepts in each condition.
  const suggestions = fieldExpressions(
    workflow,
    ["jobs", jobId],
    "if",
    manifest,
    [
      workflow as unknown as Record<string, unknown>,
      workflow.jobs,
      job as Record<string, unknown>,
    ],
  );
  const stepSuggestions = step
    ? fieldExpressions(
        workflow,
        ["jobs", jobId, "steps", index],
        "if",
        manifest,
        [
          workflow as unknown as Record<string, unknown>,
          workflow.jobs,
          job as Record<string, unknown>,
          {},
          step as Record<string, unknown>,
        ],
      )
    : [];

  return {
    fallback: null as null,
    tab,
    setTab,
    job,
    field,
    workflow,
    jobId,
    suggestions,
    stepSuggestions,
    change,
    manifest,
    index,
    onIndex,
    step,
    stepField,
    agents,
    preferences,
    defaults,
    defaultModel,
    project,
    workflowKey,
    edits,
    onEdits,
    input,
    onMove,
    loopTargets,
    onRename,
    onEditYaml,
    onOpenGetStarted,
  };
}
export type ActionJobEditorState = Extract<
  ReturnType<typeof useActionJobEditor>,
  { fallback: null }
>;
