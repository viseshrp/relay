import { useCallback, useState } from "react";
import type { AgentsResponse, AgentOptions, RepairDefaults } from "../types";
import type { RepairRuleValue, WorkflowNodeValue } from "../workflow";

export function useRepairSettings({
  stage,
  sourceOutputs,
  rule,
  defaults,
  agents,
  commands,
  model,
  preferences,
  project,
  workflowPath,
  workflowKey,
  holder,
  disabled,
  onChange,
  onSourceOutput,
  onClose,
  onApply,
  onDirty,
}: {
  stage: string;
  rule: RepairRuleValue;
  defaults: RepairDefaults;
  agents: AgentsResponse | null;
  commands: Record<string, string[]>;
  model: string;
  preferences: string[];
  project: string | null;
  workflowPath: string;
  workflowKey: string;
  holder: string;
  disabled: boolean;
  onChange: (rule: RepairRuleValue) => void;
  onClose: () => void;
  onApply: () => void;
  onDirty: (dirty: boolean) => void;
  sourceOutputs: Record<string, unknown>;
  onSourceOutput: (output: string, selector: Record<string, unknown>) => void;
}) {
  const [role, setRole] = useState<"fix" | "verify">("fix");
  const [promptDirty, setPromptDirty] = useState(false);
  const handleDirty = useCallback(
    (dirty: boolean) => {
      setPromptDirty(dirty);
      onDirty(dirty);
    },
    [onDirty],
  );
  const node = rule[role];
  const settingsDisabled = disabled || promptDirty || rule.enabled === false;
  const candidates = node.agents?.length ? node.agents : preferences;
  const selectedModel = typeof node.model === "string" ? node.model : "";
  const effectiveModel =
    selectedModel ||
    model ||
    agents?.defaults?.model ||
    agents?.defaults?.providers[candidates[0] ?? ""]?.model ||
    "";
  const resultType =
    rule.accepted_value === null
      ? "null"
      : typeof (rule.accepted_value ?? "Yes");
  // "checks.yaml", stage review, role fix -> "prompts/ui/checks/review-fix.md".
  const promptReference = `prompts/ui/${workflowKey.replace(/\.(yaml|yml)$/, "")}/${stage}-${role}.md`;
  function setNode(value: WorkflowNodeValue) {
    onChange({ ...rule, [role]: value });
  }
  function setOption(
    agentId: string,
    field: keyof AgentOptions,
    value: string | null,
  ) {
    const options = { ...node.agent_options };
    const selected = { ...options[agentId] };
    if (value !== "") selected[field] = value;
    else delete selected[field];
    if (Object.keys(selected).length) options[agentId] = selected;
    else delete options[agentId];
    setNode({ ...node, agent_options: options });
  }
  function close() {
    if (!promptDirty) onClose();
  }

  return {
    fallback: null as null,
    onClose,
    close,
    stage,
    rule,
    disabled,
    promptDirty,
    onChange,
    defaults,
    settingsDisabled,
    sourceOutputs,
    onSourceOutput,
    resultType,
    role,
    setRole,
    node,
    setNode,
    agents,
    candidates,
    selectedModel,
    project,
    model,
    effectiveModel,
    setOption,
    workflowPath,
    holder,
    promptReference,
    onDirty,
    handleDirty,
    commands,
    onApply,
  };
}
export type RepairSettingsState = Extract<
  ReturnType<typeof useRepairSettings>,
  { fallback: null }
>;
