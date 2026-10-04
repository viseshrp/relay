import {
  Alert, Box, Button, FormControl, FormHelperText, InputLabel, MenuItem,
  Select, Stack, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";

import { api, errorMessage } from "../api";
import type {
  AgentConfiguration as Configuration, AgentOptions, AgentRecord, ConfigurationSelector,
} from "../types";

interface AgentConfigurationProps {
  agent: AgentRecord;
  model: string;
  options: AgentOptions;
  onChange: (field: keyof AgentOptions, value: string) => void;
}

export function AgentConfiguration({ agent, model, options, onChange }: AgentConfigurationProps) {
  const [refresh, setRefresh] = useState(0);
  const [state, setState] = useState<{
    key: string;
    configuration: Configuration | null;
    loading: boolean;
    error: string | null;
  }>({ key: "", configuration: null, loading: false, error: null });
  const key = JSON.stringify([agent.id, model, refresh]);
  const ready = agent.installed && model !== "";
  const loading = ready && (state.key !== key || state.loading);
  const configuration = state.key === key ? state.configuration : null;
  const error = state.key === key ? state.error : null;

  useEffect(() => {
    const controller = new AbortController();
    setState({ key, configuration: null, loading: ready, error: null });
    if (ready) {
      void api<Configuration>(`/api/agents/${encodeURIComponent(agent.id)}/configuration`, {
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
  }, [agent.id, key, model, ready]);

  function selector(field: keyof AgentOptions, label: string, supported: ConfigurationSelector | null) {
    const value = options[field] ?? "";
    const choices = supported?.choices ?? [];
    const available = value === "" || choices.some((choice) => choice.value === value);
    const selected = choices.find((choice) => choice.value === value);
    const message = !agent.installed ? "Install this tool to load its supported choices."
      : !model ? "Select an exact model to load its supported choices."
      : loading ? "Loading supported choices…"
      : error ? "Supported choices could not be loaded."
      : !available ? "This saved override is unavailable for the selected model."
      : !supported ? `This tool does not expose a separate ${label.toLowerCase()} selector.`
      : supported.transport === "native" && field === "effort"
        ? "Effort is included in this exact model. Choose another model to change it."
      : selected?.description ?? (value ? `Use ${selected?.name ?? value} for this tool.`
        : "Provider default leaves this override unset.");
    const labelId = `${agent.id}-${field}-label`;
    return (
      <FormControl size="small" error={!available && !loading && !error}>
        <InputLabel id={labelId} shrink>{label}</InputLabel>
        <Select
          labelId={labelId}
          label={label}
          displayEmpty
          notched
          renderValue={(selectedValue) => selectedValue === "" ? "Provider default"
            : choices.find((choice) => choice.value === selectedValue)?.name ?? selectedValue}
          value={value}
          disabled={loading || (!supported && value === "")}
          onChange={(event) => onChange(field, event.target.value)}
        >
          <MenuItem value="">Provider default</MenuItem>
          {!available && <MenuItem value={value} disabled>{value} (unavailable)</MenuItem>}
          {choices.map((choice) => <MenuItem key={choice.value} value={choice.value}>{choice.name}</MenuItem>)}
        </Select>
        <FormHelperText>{message}</FormHelperText>
      </FormControl>
    );
  }

  return (
    <Stack component="section" aria-label={`${agent.display_name} configuration`} spacing={1.5}>
      <Typography variant="subtitle2">{agent.display_name}</Typography>
      {error && <Alert severity="error" action={<Button onClick={() => setRefresh((current) => current + 1)}>Retry</Button>}>{error}</Alert>}
      <Box className="field-grid">
        {selector("effort", "Effort", configuration?.effort ?? null)}
        {selector("permission_mode", "Permission mode", configuration?.permission_mode ?? null)}
      </Box>
    </Stack>
  );
}
