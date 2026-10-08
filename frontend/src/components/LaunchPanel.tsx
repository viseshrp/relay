import { ActionIcon } from "./ActionIcon";
import { HelpTextField, HelpSelectField } from "./HelpTip";
import { Accordion, AccordionDetails, AccordionSummary, Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack, Typography } from "@mui/material";
import { useEffect, useState } from "react";

import { api, errorMessage } from "../api";
import { projectPath, stageLabel } from "../navigation";
import type { LaunchCleanliness, OwnerSettings, PreviousRunInputs, ProjectLaunchSource, ProjectRecord } from "../types";
import type { WorkflowValue } from "../workflow";
import { LaunchInputs, type LaunchValues } from "./LaunchInputs";
import { LaunchPreflight } from "./LaunchPreflight";

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
  previousRun: PreviousRunInputs | null;
}

export function LaunchPanel({ open, workflowKey, workflow, project, requestProject, modelOptions, blockedReason, saveError, onSave, onClose, onExited, onRunLaunched, previousRun }: LaunchPanelProps) {
  const [inputs, setInputs] = useState<LaunchValues>(previousRun?.inputs ?? {});
  const [model, setModel] = useState("");
  const [cleanup, setCleanup] = useState("");
  const [defaultCleanup, setDefaultCleanup] = useState<OwnerSettings["cleanup_policy"] | null>(null);
  const [entryPoint, setEntryPoint] = useState("");
  const [source, setSource] = useState<ProjectLaunchSource | null>(null);
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [sourceRevision, setSourceRevision] = useState(0);
  const [launchError, setLaunchError] = useState<string | null>(null);
  const [launching, setLaunching] = useState(false);
  const [preflight, setPreflight] = useState<LaunchCleanliness | null>(null);
  const [preflightError, setPreflightError] = useState<string | null>(null);

  useEffect(() => { setInputs(previousRun?.inputs ?? {}); }, [previousRun]);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setSource(null);
    setDefaultCleanup(null);
    setSourceError(null);
    setLaunchError(null);
    void api<{ launch_source: ProjectLaunchSource; cleanup_policy: OwnerSettings["cleanup_policy"] }>(projectPath("/api/projects/current", requestProject), { signal: controller.signal })
      .then((response) => { if (!controller.signal.aborted) { setSource(response.launch_source); setDefaultCleanup(response.cleanup_policy); } })
      .catch((caught: unknown) => { if (!controller.signal.aborted) setSourceError(errorMessage(caught)); });
    return () => controller.abort();
  }, [open, requestProject, sourceRevision]);

  useEffect(() => {
    setPreflight(null); setPreflightError(null);
    if (!open || workflowKey === null || blockedReason || defaultCleanup === null) return;
    const controller = new AbortController();
    const path = `/api/workflows/${workflowKey.split("/").map(encodeURIComponent).join("/")}/preflight`;
    const query = `cleanup_policy=${encodeURIComponent(cleanup || defaultCleanup)}`;
    void api<LaunchCleanliness>(`${projectPath(path, requestProject)}${requestProject ? "&" : "?"}${query}`, { signal: controller.signal })
      .then((result) => { if (!controller.signal.aborted) setPreflight(result); })
      .catch((caught: unknown) => { if (!controller.signal.aborted) setPreflightError(errorMessage(caught)); });
    return () => controller.abort();
  }, [open, workflowKey, requestProject, blockedReason, sourceRevision, cleanup, defaultCleanup]);

  const reason = launching ? "Starting this workflow…" : blockedReason || (sourceError
    ? "Relay could not check the current branch. Check again before running."
    : source === null ? "Checking the current branch…"
    : source.commit === null ? "Create the first Git commit in this project before running a workflow."
    : preflightError ? "Fix the project file check, then check again before running."
    : preflight === null ? "Checking project files…"
    : !preflight.clean ? `${preflight.blocking_count} ${preflight.blocking_count === 1 ? "file blocks" : "files block"} this run. Commit or set aside the listed changes first.` : null);

  async function launch(): Promise<void> {
    if (reason || workflowKey === null) return;
    setLaunching(true);
    setLaunchError(null);
    try {
      // Untouched values stay omitted so defaults are resolved by the service.
      const supplied = Object.fromEntries(Object.entries(inputs).filter(([name, value]) => value !== undefined && Object.hasOwn(workflow?.inputs ?? {}, name)));
      const response = await api<{ run_id: string }>(projectPath("/api/runs", requestProject), {
        method: "POST", body: JSON.stringify({ workflow_key: workflowKey, project_id: project.id, inputs: supplied,
          ...(model ? { model } : {}), ...(cleanup ? { cleanup_policy: cleanup } : {}), ...(entryPoint ? { entry_point: entryPoint } : {}) }),
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
        {previousRun && <Alert severity="info">Previous inputs are prefilled. This creates a new run using the saved workflow, current branch, and fresh agent checks. Changed input definitions are validated again.</Alert>}
        {source?.commit && <Typography>Runs on a new branch from <strong>{source.branch ?? `commit ${source.commit.slice(0, 12)}`}</strong>.</Typography>}
        {(cleanup || defaultCleanup) === "merge_on_success" && <Alert severity="info">After every job succeeds, Relay will fast-forward {source?.branch ?? "the branch selected at launch"} and delete the run working copies. The checkout must stay completely clean and on that branch.</Alert>}
        {sourceError && <Alert severity="error">{sourceError}</Alert>}
        {reason && <Alert severity="info" action={onSave ? <Button onClick={onSave}>Save</Button>
          : sourceError ? <Button onClick={() => setSourceRevision((value) => value + 1)}>Check again</Button> : undefined}>{reason}</Alert>}
        {saveError && <Alert severity="error">{saveError}</Alert>}
        {launchError && <Alert severity="error">{launchError}</Alert>}
        {!blockedReason && <LaunchPreflight result={preflight} error={preflightError} onCheck={() => setSourceRevision((value) => value + 1)} />}
        <LaunchInputs definitions={workflow?.inputs ?? {}} values={inputs} onChange={(name, value) => setInputs((current) => ({ ...current, [name]: value }))} />
        <Accordion><AccordionSummary expandIcon={<ActionIcon name="down" />}>Advanced options</AccordionSummary><AccordionDetails><Stack spacing={2}>
          <HelpTextField topic="model" label="Override model for this run" placeholder="Use workflow, project, and global defaults" value={model} onChange={(event) => setModel(event.target.value)} helperText="Leave blank to use the workflow, project, or global model. Values must match the provider exactly, including case." slotProps={{ htmlInput: { list: "launch-model-options" } }} />
          <datalist id="launch-model-options">{modelOptions.map((value) => <option key={value} value={value} />)}</datalist>
          <HelpSelectField topic="cleanup" label="After a successful run" fullWidth value={cleanup} onChange={(event) => setCleanup(event.target.value)} helperText={<> {cleanup === "merge_on_success" ? "Fast-forwards the branch shown above after every job succeeds. Commit all workflow, report, and code changes first. Dirty, switched, or diverged branches fail and keep the run working copy." : "Saved reports and committed changes remain available after the working copy is deleted."} </>}>
              <MenuItem value="">Use project and global defaults</MenuItem><MenuItem value="clean_on_success">Delete the working copy</MenuItem><MenuItem value="retain">Keep the working copy</MenuItem><MenuItem value="merge_on_success">Merge into the active branch, then delete working copies</MenuItem>
            </HelpSelectField>
          <HelpSelectField topic="entry" label="Start from job" fullWidth value={entryPoint} onChange={(event) => setEntryPoint(event.target.value)} helperText={<> Only jobs declared as start points are listed. Relay checks their required inputs and saved reports before starting. </>}>
              <MenuItem value="">Start at the beginning</MenuItem>
              {(workflow?.entrypoints ?? []).map((entry) => <MenuItem key={entry.scope_path} value={entry.scope_path}>{stageLabel(entry.scope_path)}</MenuItem>)}
            </HelpSelectField>
        </Stack></AccordionDetails></Accordion>
      </Stack></DialogContent>
      <DialogActions><Button onClick={onClose} disabled={launching}>Cancel</Button>
        <Button type="submit" variant="contained" disabled={reason !== null}>{launching ? "Starting…" : "Run workflow"}</Button>
      </DialogActions>
    </form>
  </Dialog>;
}
