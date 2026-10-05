import {
  Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle,
  FormControl, InputLabel, LinearProgress, MenuItem, Select, Stack, TextField, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";

import { api, errorMessage } from "../api";
import { projectPath, stageLabel } from "../navigation";
import type { AgentConfiguration, AgentsResponse, ModelObservation, RetryConfiguration, RetryOptions } from "../types";

type RetryModel = Pick<ModelObservation, "value" | "name">;

export function RetrySettings({ problem, projectId, onClose, onRetry }: {
  problem: RetryConfiguration;
  projectId: string;
  onClose: () => void;
  onRetry: (scope: string, options?: RetryOptions) => Promise<void>;
}) {
  const [agents, setAgents] = useState<AgentsResponse | null>(null);
  const [agentId, setAgentId] = useState(problem.agent_id);
  const [model, setModel] = useState(problem.model_value);
  const [models, setModels] = useState<{ agentId: string; choices: RetryModel[] } | null>(null);
  const [state, setState] = useState<{ key: string; configuration: AgentConfiguration | null }>({ key: "", configuration: null });
  const [selection, setSelection] = useState(0);
  const [permissionSelection, setPermissionSelection] = useState(0);
  const [handoff, setHandoff] = useState(problem.default_handoff_prompt ?? "");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const changed = model !== "" && (agentId !== problem.agent_id || model !== problem.model_value);
  const key = JSON.stringify([agentId, model, projectId]);
  const configuration = state.key === key ? state.configuration : null;
  const handoffTooLong = problem.handoff_prompt_max_bytes !== undefined
    && new TextEncoder().encode(handoff).length > problem.handoff_prompt_max_bytes;

  useEffect(() => {
    const controller = new AbortController();
    void api<AgentsResponse>("/api/agents", { signal: controller.signal }).then((value) => {
      if (!controller.signal.aborted) setAgents(value);
    }).catch((caught) => {
      if (!controller.signal.aborted) setError(errorMessage(caught));
    });
    return () => controller.abort();
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void api<{ models: RetryModel[] }>(
      projectPath(`/api/agents/${encodeURIComponent(agentId)}/models`, projectId),
      { method: "POST", body: "{}", signal: controller.signal },
    ).then((value) => {
      if (!controller.signal.aborted) setModels({ agentId, choices: value.models });
    }).catch((caught) => {
      if (!controller.signal.aborted) setError(errorMessage(caught));
    });
    return () => controller.abort();
  }, [agentId, projectId]);

  useEffect(() => {
    const controller = new AbortController();
    if (!model) return () => controller.abort();
    void api<AgentConfiguration>(
      projectPath(`/api/agents/${encodeURIComponent(agentId)}/configuration`, projectId),
      { method: "POST", body: JSON.stringify({ model }), signal: controller.signal },
    ).then((value) => {
      if (!controller.signal.aborted) setState({ key, configuration: value });
    }).catch((caught) => {
      if (!controller.signal.aborted) setError(errorMessage(caught));
    });
    return () => controller.abort();
  }, [agentId, model, key, projectId]);
  const selector = configuration?.effort;
  const editable = selector !== null && selector !== undefined && selector.transport !== "native";
  const choices = models?.agentId === agentId ? models.choices : [];

  function changeAgent(value: string) {
    setAgentId(value);
    setModel("");
    setSelection(1);
    setPermissionSelection(1);
    setState({ key: "", configuration: null });
    setError(null);
  }

  function changeModel(value: string) {
    setModel(value);
    setSelection(value === problem.model_value && agentId === problem.agent_id ? 0 : 1);
    setPermissionSelection(value === problem.model_value && agentId === problem.agent_id ? 0 : 1);
    setState({ key: "", configuration: null });
    setError(null);
  }

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      const effort = selection === 0 ? undefined : selection === 1 ? null : selector?.choices[selection - 2]?.value;
      const permission = permissionSelection === 0 ? undefined : permissionSelection === 1 ? null
        : configuration?.permission_mode?.choices[permissionSelection - 2]?.value;
      await onRetry(problem.scope_path, changed ? {
        agent_id: agentId, model, effort: editable ? effort ?? null : null,
        permission_mode: permission ?? null, handoff_prompt: handoff,
      } : { effort, permission_mode: permission });
      onClose();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setSubmitting(false);
    }
  }

  return <Dialog open onClose={submitting ? undefined : onClose} fullWidth maxWidth="sm">
    <DialogTitle>Retry {stageLabel(problem.scope_path)} with settings</DialogTitle>
    <DialogContent>
      <Stack spacing={2} sx={{ pt: 1 }}>
        <Typography variant="body2">
          Choose the tool and model for this step's new attempts. Completed steps,
          prompts, and earlier attempts stay saved. Automatic retries keep your choice.
        </Typography>
        <FormControl fullWidth disabled={!agents || submitting}>
          <InputLabel id="retry-agent-label">Tool</InputLabel>
          <Select labelId="retry-agent-label" label="Tool" value={agentId}
            onChange={(event) => changeAgent(event.target.value)}>
            {!agents && <MenuItem value={problem.agent_id}>{stageLabel(problem.agent_id)}</MenuItem>}
            {agents?.agents.map((agent) => <MenuItem key={agent.id} value={agent.id} disabled={!agent.installed}>
              {agent.display_name}{agent.installed ? "" : " (not installed)"}
            </MenuItem>)}
          </Select>
        </FormControl>
        <FormControl fullWidth disabled={models?.agentId !== agentId || submitting}>
          <InputLabel id="retry-model-label">Model</InputLabel>
          <Select labelId="retry-model-label" label="Model" value={model}
            onChange={(event) => changeModel(event.target.value)}>
            {model && !choices.some((choice) => choice.value === model) && <MenuItem value={model}>{model}</MenuItem>}
            {choices.map((choice) => <MenuItem key={choice.value} value={choice.value}>{choice.name}</MenuItem>)}
          </Select>
        </FormControl>
        {!configuration && !error && <LinearProgress aria-label="Loading effort choices" />}
        {error && <Alert severity="error">{error}</Alert>}
        {configuration && <FormControl fullWidth disabled={!editable || submitting}>
          <InputLabel id="retry-effort-label">Effort</InputLabel>
          <Select<number> labelId="retry-effort-label" label="Effort" value={selection}
            onChange={(event) => setSelection(Number(event.target.value))}>
            {!changed && <MenuItem value={0}>Keep current effort ({problem.effort ?? "Provider default"})</MenuItem>}
            <MenuItem value={1}>Provider default</MenuItem>
            {editable && selector.choices.map((choice, index) => <MenuItem key={choice.value} value={index + 2}>
              {choice.name}
            </MenuItem>)}
          </Select>
        </FormControl>}
        {configuration && !editable && <Typography variant="body2" color="text.secondary">
          {selector?.transport === "native" ? `Effort is ${selector.current_value}, included in this model.`
            : "This model does not offer a separate effort setting."}
        </Typography>}
        {configuration && <FormControl fullWidth disabled={!configuration.permission_mode || submitting}>
          <InputLabel id="retry-permission-label">Permission mode</InputLabel>
          <Select<number> labelId="retry-permission-label" label="Permission mode" value={permissionSelection}
            onChange={(event) => setPermissionSelection(Number(event.target.value))}>
            {!changed && <MenuItem value={0}>Keep current permission mode ({problem.permission_mode ?? "Provider default"})</MenuItem>}
            <MenuItem value={1}>Provider default</MenuItem>
            {configuration.permission_mode?.choices.map((choice, index) => <MenuItem key={choice.value} value={index + 2}>{choice.name}</MenuItem>)}
          </Select>
        </FormControl>}
        {changed && <>
          <TextField label="Handoff instructions" multiline minRows={4} value={handoff} disabled={submitting}
            error={handoffTooLong}
            helperText={handoffTooLong ? `Use at most ${problem.handoff_prompt_max_bytes} UTF-8 bytes.`
              : "These instructions follow this step's original prompts. Edit them to tell the new model how to continue."}
            onChange={(event) => setHandoff(event.target.value)} />
          <Button disabled={submitting} onClick={() => setHandoff(problem.default_handoff_prompt ?? "")}>Use default handoff</Button>
        </>}
      </Stack>
    </DialogContent>
    <DialogActions>
      <Button disabled={submitting} onClick={onClose}>Cancel</Button>
      <Button variant="contained" disabled={!configuration || submitting || (changed && (!handoff.trim() || handoffTooLong))} onClick={() => void submit()}>
        {submitting ? "Starting retry…" : "Retry with settings"}
      </Button>
    </DialogActions>
  </Dialog>;
}
