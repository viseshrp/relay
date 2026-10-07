import { Alert, Button, FormControl, InputLabel, MenuItem, Select, Stack } from "@mui/material";
import { useId, useState } from "react";
import { api, errorMessage } from "../api";
import { projectPath } from "../navigation";
import type { AgentRecord } from "../types";

export function ModelPicker({ agents, value, project, disabled = false, onChange }: {
  agents: AgentRecord[]; value: string; project: string | null; onChange: (value: string) => void;
  disabled?: boolean;
}) {
  const labelId = useId();
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
  return <Stack spacing={1}>
    <FormControl size="small"><InputLabel id={labelId}>Model</InputLabel><Select labelId={labelId} label="Model" value={value} disabled={disabled || busy} onChange={(event) => onChange(event.target.value)}>
      <MenuItem value="">Use workflow model</MenuItem>
      {value && !models.has(value) && <MenuItem value={value}>{value}</MenuItem>}
      {Array.from(models, ([id, name]) => <MenuItem key={id} value={id}>{name}</MenuItem>)}
    </Select></FormControl>
    <Button disabled={disabled || busy || agents.every((agent) => !agent.installed)} onClick={() => void load()}>{busy ? "Loading models…" : "Load available models"}</Button>
    {error && <Alert severity="error" sx={{ whiteSpace: "pre-wrap" }}>{error}</Alert>}
  </Stack>;
}
