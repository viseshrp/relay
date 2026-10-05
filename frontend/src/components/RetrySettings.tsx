import {
  Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle,
  FormControl, InputLabel, LinearProgress, MenuItem, Select, Stack, Typography,
} from "@mui/material";
import { useEffect, useState } from "react";

import { api, errorMessage } from "../api";
import { stageLabel } from "../navigation";
import type { AgentConfiguration, RunProblem } from "../types";

export function RetrySettings({ problem, projectId, onClose, onRetry }: {
  problem: RunProblem;
  projectId: string;
  onClose: () => void;
  onRetry: (scope: string, effort?: string | null) => Promise<void>;
}) {
  const [configuration, setConfiguration] = useState<AgentConfiguration | null>(null);
  const [selection, setSelection] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    void api<AgentConfiguration>(
      `/api/agents/${encodeURIComponent(problem.agent_id)}/configuration?project=${encodeURIComponent(projectId)}`,
      { method: "POST", body: JSON.stringify({ model: problem.model_value }), signal: controller.signal },
    ).then(setConfiguration).catch((caught) => {
      if (!controller.signal.aborted) setError(errorMessage(caught));
    });
    return () => controller.abort();
  }, [problem.agent_id, problem.model_value, projectId]);
  const selector = configuration?.effort;
  const editable = selector !== null && selector !== undefined && selector.transport !== "native";

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      const effort = selection === 0 ? undefined : selection === 1 ? null : selector?.choices[selection - 2]?.value;
      await onRetry(problem.scope_path, effort);
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
        <Typography>{stageLabel(problem.agent_id)} · {problem.model_value}</Typography>
        <Typography variant="body2">
          This changes effort for this step's new attempts. Completed steps, prompts,
          and earlier attempts stay saved. Automatic retries keep your choice.
        </Typography>
        {!configuration && !error && <LinearProgress aria-label="Loading effort choices" />}
        {error && <Alert severity="error">{error}</Alert>}
        {configuration && <FormControl fullWidth disabled={!editable || submitting}>
          <InputLabel id="retry-effort-label">Effort</InputLabel>
          <Select<number> labelId="retry-effort-label" label="Effort" value={selection}
            onChange={(event) => setSelection(Number(event.target.value))}>
            <MenuItem value={0}>Keep current effort ({problem.effort ?? "Provider default"})</MenuItem>
            {editable && <MenuItem value={1}>Provider default</MenuItem>}
            {editable && selector.choices.map((choice, index) => <MenuItem key={choice.value} value={index + 2}>
              {choice.name}
            </MenuItem>)}
          </Select>
        </FormControl>}
        {configuration && !editable && <Typography variant="body2" color="text.secondary">
          This model does not offer a separate effort setting.
        </Typography>}
      </Stack>
    </DialogContent>
    <DialogActions>
      <Button disabled={submitting} onClick={onClose}>Cancel</Button>
      <Button variant="contained" disabled={!configuration || submitting} onClick={() => void submit()}>
        {submitting ? "Starting retry…" : "Retry with settings"}
      </Button>
    </DialogActions>
  </Dialog>;
}
