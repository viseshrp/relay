import type { AgentsResponse, RepairDefaults } from "../types";
import type { RepairRuleValue } from "../workflow";

import { useRepairSettings } from "./useRepairSettings";
import { RepairSettingsView } from "./RepairSettingsView";
export function RepairSettings(props: {
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
  const state = useRepairSettings(props);
  if (state.fallback !== null) return state.fallback;
  return <RepairSettingsView state={state} />;
}
