import { Accordion, AccordionDetails, AccordionSummary, Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControl, FormHelperText, InputLabel, MenuItem, Select, Stack, TextField, Typography } from "@mui/material";
import { useEffect, useState } from "react";

import { api, errorMessage } from "../api";
import { projectPath, stageLabel } from "../navigation";
import type { ProjectLaunchSource, ProjectRecord } from "../types";
import type { WorkflowValue } from "../workflow";
import { LaunchInputs, type LaunchValues } from "./LaunchInputs";

interface LaunchPanelProps {
  open: boolean;
  workflowKey: string | null;
  workflow: WorkflowValue | null;
  project: ProjectRecord;
  requestProject: string | null;
  modelOptions: string[];
  blockedReason: string | null;
  saveError: string | null;
  onSave?: () => void;
  onClose: () => void;
  onExited: () => void;
  onRunLaunched: (runId: string) => void;
}

export function LaunchPanel({ open, workflowKey, workflow, project, requestProject, modelOptions, blockedReason, saveError, onSave, onClose, onExited, onRunLaunched }: LaunchPanelProps) {
  const [inputs, setInputs] = useState<LaunchValues>({});
  const [model, setModel] = useState("");
  const [cleanup, setCleanup] = useState("clean_on_success");
  const [entryPoint, setEntryPoint] = useState("");
  const [source, setSource] = useState<ProjectLaunchSource | null>(null);
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [sourceRevision, setSourceRevision] = useState(0);
  const [launchError, setLaunchError] = useState<string | null>(null);
  const [launching, setLaunching] = useState(false);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setSource(null);
    setSourceError(null);
    setLaunchError(null);
    void api<{ launch_source: ProjectLaunchSource }>(projectPath("/api/projects/current", requestProject), { signal: controller.signal })
      .then((response) => { if (!controller.signal.aborted) setSource(response.launch_source); })
      .catch((caught: unknown) => { if (!controller.signal.aborted) setSourceError(errorMessage(caught)); });
    return () => controller.abort();
  }, [open, requestProject, sourceRevision]);

  const reason = launching ? "Starting this workflow…" : blockedReason || (sourceError
    ? "Relay could not check the current branch. Check again before running."
    : source === null ? "Checking the current branch…"
    : source.commit === null ? "Create the first Git commit in this project before running a workflow." : null);

  async function launch(): Promise<void> {
    if (reason || workflowKey === null) return;
    setLaunching(true);
    setLaunchError(null);
    try {
      // Untouched values stay omitted so defaults are resolved by the service.
      const supplied = Object.fromEntries(Object.entries(inputs).filter(([name, value]) => value !== undefined && Object.hasOwn(workflow?.inputs ?? {}, name)));
      const response = await api<{ run_id: string }>(projectPath("/api/runs", requestProject), {
        method: "POST", body: JSON.stringify({ workflow_key: workflowKey, project_id: project.id, inputs: supplied,
          ...(model ? { model } : {}), cleanup_policy: cleanup, ...(entryPoint ? { entry_point: entryPoint } : {}) }),
      });
      onRunLaunched(response.run_id);
    } catch (caught) { setLaunchError(errorMessage(caught)); }
    finally { setLaunching(false); }
  }

  return <Dialog open={open} onClose={() => { if (!launching) onClose(); }} fullWidth maxWidth="sm"
    slotProps={{ transition: { onExited } }} aria-labelledby="launch-title">
    <DialogTitle id="launch-title">Run workflow</DialogTitle>
    <form onSubmit={(event) => { event.preventDefault(); void launch(); }}>
      <DialogContent><Stack spacing={2}>
        <Typography variant="h6">{workflow?.name ?? "Choose a workflow"}</Typography>
        {source?.commit && <Typography>Runs on a new branch from <strong>{source.branch ?? `commit ${source.commit.slice(0, 12)}`}</strong>.</Typography>}
        {sourceError && <Alert severity="error">{sourceError}</Alert>}
        {reason && <Alert severity="info" action={onSave ? <Button onClick={onSave}>Save</Button>
          : sourceError ? <Button onClick={() => setSourceRevision((value) => value + 1)}>Check again</Button> : undefined}>{reason}</Alert>}
        {saveError && <Alert severity="error">{saveError}</Alert>}
        {launchError && <Alert severity="error">{launchError}</Alert>}
        <LaunchInputs definitions={workflow?.inputs ?? {}} values={inputs} onChange={(name, value) => setInputs((current) => ({ ...current, [name]: value }))} />
        <Accordion><AccordionSummary>Advanced options</AccordionSummary><AccordionDetails><Stack spacing={2}>
          <TextField label="Override model for this run" value={model} onChange={(event) => setModel(event.target.value)}
            helperText="Leave blank to use the workflow's model. Values must match the provider exactly, including case."
            slotProps={{ htmlInput: { list: "launch-model-options" } }} />
          <datalist id="launch-model-options">{modelOptions.map((value) => <option key={value} value={value} />)}</datalist>
          <FormControl fullWidth><InputLabel id="launch-cleanup">After a successful run</InputLabel>
            <Select labelId="launch-cleanup" label="After a successful run" value={cleanup} onChange={(event) => setCleanup(event.target.value)}>
              <MenuItem value="clean_on_success">Delete the working copy</MenuItem><MenuItem value="retain">Keep the working copy</MenuItem>
            </Select><FormHelperText>Saved reports and committed changes remain available after the working copy is deleted.</FormHelperText>
          </FormControl>
          <FormControl fullWidth><InputLabel id="launch-entry">Start from job</InputLabel>
            <Select labelId="launch-entry" label="Start from job" value={entryPoint} onChange={(event) => setEntryPoint(event.target.value)}>
              <MenuItem value="">Start at the beginning</MenuItem>
              {(workflow?.entrypoints ?? []).map((entry) => <MenuItem key={entry.scope_path} value={entry.scope_path}>{stageLabel(entry.scope_path)}</MenuItem>)}
            </Select><FormHelperText>Only jobs declared as start points are listed. Relay checks their required inputs and saved reports before starting.</FormHelperText>
          </FormControl>
        </Stack></AccordionDetails></Accordion>
      </Stack></DialogContent>
      <DialogActions><Button onClick={onClose} disabled={launching}>Cancel</Button>
        <Button type="submit" variant="contained" disabled={reason !== null}>{launching ? "Starting…" : "Run workflow"}</Button>
      </DialogActions>
    </form>
  </Dialog>;
}
