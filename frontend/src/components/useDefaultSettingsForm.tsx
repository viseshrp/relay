import { settingsErrors } from "../settings-validation";

import { HelpControl } from "./HelpTip";
import { Box, FormControlLabel, Switch, Typography } from "@mui/material";
import { useId, useState } from "react";
import type {
  OwnerSettings,
  ProviderDefaults,
  WorkflowDefaults,
} from "../types";

import { Props, overrideLabels } from "./DefaultSettingsFormShared";
export function useDefaultSettingsForm({
  settings,
  agents,
  onChange,
  project,
  disabled,
  overrides,
  onOverrides,
  tourActive = false,
}: Props) {
  const prefix = useId();
  const [repairOpen, setRepairOpen] = useState(false);
  const defaults = settings.workflow_defaults;
  const errors = settingsErrors(settings);
  const projectMode = overrides !== undefined;
  function update<K extends keyof WorkflowDefaults>(
    key: K,
    value: WorkflowDefaults[K],
  ) {
    onChange({ ...settings, workflow_defaults: { ...defaults, [key]: value } });
    onOverrides?.({
      ...overrides,
      workflow_defaults: { ...overrides?.workflow_defaults, [key]: value },
    });
  }
  function ownerUpdate<K extends "agent_preferences" | "cleanup_policy">(
    key: K,
    value: OwnerSettings[K],
  ) {
    onChange({ ...settings, [key]: value });
    onOverrides?.({ ...overrides, [key]: value });
  }
  function inherit(
    key: keyof WorkflowDefaults | "agent_preferences" | "cleanup_policy",
  ) {
    if (!onOverrides || !overrides) return null;
    const root = key === "agent_preferences" || key === "cleanup_policy";
    const selected = Object.hasOwn(
      root ? overrides : (overrides.workflow_defaults ?? {}),
      key,
    );
    return (
      <Box className="project-override">
        <HelpControl topic="override">
          <FormControlLabel
            control={
              <Switch
                size="small"
                slotProps={{
                  input: {
                    "aria-label": `Override ${overrideLabels[key]} for this project`,
                  },
                }}
                checked={selected}
                disabled={disabled}
                onChange={(_event, checked) => {
                  const next = {
                    ...overrides,
                    workflow_defaults: { ...overrides.workflow_defaults },
                  };
                  if (root) {
                    if (checked) Object.assign(next, { [key]: settings[key] });
                    else delete next[key];
                  } else if (checked)
                    Object.assign(next.workflow_defaults, {
                      [key]: defaults[key],
                    });
                  else delete next.workflow_defaults[key];
                  onOverrides(next);
                }}
              />
            }
            label="Override for this project"
          />
        </HelpControl>
        <Typography variant="caption" color="text.secondary">
          {selected ? "Project override" : "Using global default"}
        </Typography>
      </Box>
    );
  }
  function locked(
    key: keyof WorkflowDefaults | "agent_preferences" | "cleanup_policy",
  ) {
    return (
      disabled ||
      (projectMode &&
        !Object.hasOwn(
          key === "agent_preferences" || key === "cleanup_policy"
            ? overrides
            : (overrides.workflow_defaults ?? {}),
          key,
        ))
    );
  }
  function providerChange(id: string, value: ProviderDefaults) {
    update("providers", { ...defaults.providers, [id]: value });
  }

  return {
    fallback: null as null,
    inherit,
    settings,
    agents,
    disabled,
    locked,
    ownerUpdate,
    prefix,
    onChange,
    defaults,
    update,
    project,
    providerChange,
    errors,
    tourActive,
    repairOpen,
    setRepairOpen,
  };
}
export type DefaultSettingsFormState = Extract<
  ReturnType<typeof useDefaultSettingsForm>,
  { fallback: null }
>;
