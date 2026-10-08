import { HelpField } from "./HelpTip";
import {
  Alert, Box, Button, FormControl, FormHelperText, InputLabel, MenuItem,
  Select, Stack, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";

import { api, errorMessage } from "../api";
import { projectPath } from "../navigation";
import type {
  AgentConfiguration as Configuration, AgentOptions, AgentRecord, ConfigurationSelector,
} from "../types";

interface AgentConfigurationProps {
  agent: AgentRecord;
  model: string;
  options: AgentOptions;
  onChange: (field: keyof AgentOptions, value: string | null) => void;
  project: string | null;
  disabled?: boolean;
  defaultLabel?: string;
  inheritDefaults?: boolean;
  labels?: Record<keyof AgentOptions, string>;
}

export function AgentConfiguration({ agent, model, options, onChange, project, disabled = false, labels, defaultLabel = "Provider default", inheritDefaults = false }: AgentConfigurationProps) {
  const [refresh, setRefresh] = useState(0);
  const [state, setState] = useState<{
    key: string;
    configuration: Configuration | null;
    loading: boolean;
    error: string | null;
  }>({ key: "", configuration: null, loading: false, error: null });
  const key = JSON.stringify([agent.id, model, refresh, project]);
  const ready = agent.installed && model !== "";
  const loading = ready && (state.key !== key || state.loading);
  const configuration = state.key === key ? state.configuration : null;
  const error = state.key === key ? state.error : null;

  useEffect(() => {
    const controller = new AbortController();
    setState({ key, configuration: null, loading: ready, error: null });
    if (ready) {
      void api<Configuration>(projectPath(`/api/agents/${encodeURIComponent(agent.id)}/configuration`, project), {
        method: "POST",
        body: JSON.stringify({ model }),
        signal: controller.signal,
      }).then((value) => {
        if (!controller.signal.aborted) {
          setState({ key, configuration: value, loading: false, error: null });
        }
      }).catch((caught: unknown) => {
        if (!controller.signal.aborted) {
          setState({ key, configuration: null, loading: false, error: errorMessage(caught) });
        }
      });
    }
    return () => controller.abort();
  }, [agent.id, key, model, ready, project]);

  function selector(field: keyof AgentOptions, label: string, supported: ConfigurationSelector | null) {
    const raw = options[field];
    const value = raw === null ? "agent-default" : raw === undefined ? "inherit" : `choice:${raw}`;
    const choices = supported?.choices ?? [];
    const available = raw === undefined || raw === null || choices.some((choice) => choice.value === raw);
    const selected = choices.find((choice) => choice.value === raw);
    const message = !agent.installed ? "Install this tool to load its supported choices."
      : !model ? "Select an exact model to load its supported choices."
      : loading ? "Loading supported choices…"
      : error ? "Supported choices could not be loaded."
      : !available ? "This saved override is unavailable for the selected model."
      : !supported ? `This tool does not expose a separate ${label.toLowerCase()} selector.`
      : supported.transport === "native" && field === "effort"
        ? "Effort is included in this exact model. Choose another model to change it."
      : selected?.description ?? (raw ? `Use ${selected?.name ?? raw} for this tool.`
        : inheritDefaults && raw === undefined ? "Use the saved defaults for this exact model." : `${defaultLabel} leaves this override unset.`);
    const labelId = `${agent.id}-${field}-label`;
    return (
      <HelpField topic={field === "effort" ? "effort" : "permissions"}><FormControl fullWidth size="small" error={!available && !loading && !error}>
        <InputLabel id={labelId} shrink>{label}</InputLabel>
        <Select
          labelId={labelId}
          label={label}
          displayEmpty
          notched
          renderValue={(selectedValue) => selectedValue === "inherit" ? (inheritDefaults ? "Use project and global defaults" : defaultLabel)
            : selectedValue === "agent-default" ? "Agent’s default"
            : choices.find((choice) => choice.value === selectedValue.slice(7))?.name ?? selectedValue.slice(7)}
          value={value}
          disabled={disabled || loading || (!supported && raw === undefined)}
          onChange={(event) => onChange(field, event.target.value === "agent-default" ? null : event.target.value === "inherit" ? "" : event.target.value.slice(7))}
        >
          <MenuItem value="inherit">{inheritDefaults ? "Use project and global defaults" : defaultLabel}</MenuItem>
          {(inheritDefaults || options[field] === null) && <MenuItem value="agent-default">Agent’s default</MenuItem>}
          {!available && <MenuItem value={value} disabled>{raw} (unavailable)</MenuItem>}
          {choices.map((choice) => <MenuItem key={choice.value} value={`choice:${choice.value}`}>{choice.name}</MenuItem>)}
        </Select>
        <FormHelperText>{message}</FormHelperText>
      </FormControl></HelpField>
    );
  }

  return (
    <Stack component="section" aria-label={`${agent.display_name} configuration`} spacing={1.5}>
      <Typography variant="subtitle2">{agent.display_name}</Typography>
      {error && <Alert severity="error" action={<Button disabled={disabled} onClick={() => setRefresh((current) => current + 1)}>Retry</Button>}>{error}</Alert>}
      <Box className="field-grid">
        {selector("effort", labels?.effort ?? "Effort", configuration?.effort ?? null)}
        {selector("permission_mode", labels?.permission_mode ?? "Permission mode", configuration?.permission_mode ?? null)}
      </Box>
    </Stack>
  );
}
