import { Alert, Autocomplete, Button, Stack, TextField } from "@mui/material";
import { useState } from "react";
import { api, errorMessage } from "../api";
import { projectPath } from "../navigation";
import type { AgentRecord } from "../types";

export function ModelPicker({ agents, value, project, disabled = false, onChange, defaultLabel = "Use workflow model" }: {
  agents: AgentRecord[]; value: string; project: string | null; onChange: (value: string) => void;
  disabled?: boolean; defaultLabel?: string;
}) {
  const [observed, setObserved] = useState<Array<{ value: string; name: string }>>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const models = new Map([...agents.flatMap((agent) => agent.models), ...observed].map((item) => [item.value, item.name]));
  async function load() {
    setBusy(true); setError(null);
    const results = await Promise.allSettled(agents.filter((agent) => agent.installed).map((agent) => api<{ models: Array<{ value: string; name: string }> }>(projectPath(`/api/agents/${agent.id}/models`, project), { method: "POST", body: "{}" })));
    const failures: string[] = []; const available: Array<{ value: string; name: string }> = [];
    for (const result of results) {
      if (result.status === "fulfilled") available.push(...result.value.models);
      else failures.push(errorMessage(result.reason));
    }
    setObserved(available); setError(failures.join("\n") || (available.length ? null : "No models were returned. Check that a selected tool is installed and signed in.")); setBusy(false);
  }
  return <Stack spacing={1} className="model-picker">
    <Autocomplete freeSolo value={value} options={[...models.keys()]} disabled={disabled || busy} getOptionLabel={id => models.get(id) || id} onChange={(_, selected) => onChange(selected ?? "")} onInputChange={(_, input, reason) => { if (reason === "input") onChange(input); }} renderInput={parameters => <TextField {...parameters} label="Model" size="small" placeholder={defaultLabel} helperText={value ? `Exact provider value: ${value}` : defaultLabel} />} />
    <Button sx={{ alignSelf: "flex-start" }} disabled={disabled || busy || agents.every((agent) => !agent.installed)} onClick={() => void load()}>{busy ? "Loading models…" : "Load available models"}</Button>
    {error && <Alert severity="error" sx={{ whiteSpace: "pre-wrap" }}>{error}</Alert>}
  </Stack>;
}
