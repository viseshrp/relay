import { HelpLabel, HelpSelectField } from "./HelpTip";
import { Alert, Box, Button, CircularProgress, Dialog, DialogActions, DialogContent, DialogTitle, MenuItem, Stack, TextField, Typography } from "@mui/material";
import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import { projectPath } from "../navigation";
import type { ProjectRecord, StorageUsage } from "../types";
import { TemporaryResourceCleanup } from "./TemporaryResourceCleanup";

const scopes = {
  worktrees: { label: "Working copies", description: "Folders Relay used to run jobs. Your repository is not touched. Evidence is preserved before removal." },
  branches: { label: "Run branches and saved refs", description: "Git references retained for runs and attempts. Remove working copies first. Your launch branch stays in place." },
  runs: { label: "Run history and reports", description: "Run records, snapshots, logs, approvals, and saved reports. Remove working copies and run references first." },
  all: { label: "Everything for this project", description: "Working copies, run references, history, and reports, in that order. Also clears Relay's marked process logs across the installation." },
} as const;
type Scope = keyof typeof scopes;
function isScope(value: string): value is Scope { return Object.hasOwn(scopes, value); }
function size(bytes: number): string { return bytes < 1024 ? `${bytes} B` : bytes < 1024 * 1024 ? `${(bytes / 1024).toFixed(1)} KiB` : `${(bytes / 1024 / 1024).toFixed(1)} MiB`; }
function count(value: number, singular: string): string { return `${value} ${singular}${value === 1 ? "" : "s"}`; }

function StorageMetric({ label, value, detail, description }: { label: string; value: string; detail?: string; description: string }) {
  return <Box className="storage-metric"><Typography component="dt">{label}</Typography><Box component="dd"><Box className="storage-values"><Typography className="storage-total">{value}</Typography>{detail && <Typography className="storage-size">{detail}</Typography>}</Box><Box component="details" className="storage-explanation"><Box component="summary">About {label.toLowerCase()}</Box><Typography variant="body2" color="text.secondary">{description}</Typography></Box></Box></Box>;
}

export function StorageSettings({ project, requestProject }: { project: ProjectRecord; requestProject: string | null }) {
  const [usage, setUsage] = useState<StorageUsage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [revision, setRevision] = useState(0);
  const [scope, setScope] = useState<Scope | "">("");
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController(); setError(null); setUsage(null);
    void api<StorageUsage>(projectPath("/api/data/usage", requestProject), { signal: controller.signal })
      .then((value) => { if (!controller.signal.aborted) setUsage(value); })
      .catch((caught: unknown) => { if (!controller.signal.aborted) setError(errorMessage(caught)); });
    return () => controller.abort();
  }, [project.id, requestProject, revision]);
  async function clean(): Promise<void> {
    if (!scope || !usage || usage.cleanup_blocked || (scope === "all" && name !== project.display_name)) return;
    setBusy(true); setError(null);
    try {
      const result = await api<{ deleted: Record<string, number> }>(projectPath("/api/data/clean", requestProject), { method: "POST", body: JSON.stringify({ scope, confirm: true }) });
      setNotice(`Removed ${result.deleted.worktrees ?? 0} working copies, ${result.deleted.branches ?? 0} branches, and ${result.deleted.runs ?? 0} runs.`);
      setOpen(false); setScope(""); setName(""); setRevision((value) => value + 1);
    } catch (caught) { setError(errorMessage(caught)); }
    finally { setBusy(false); }
  }
  return <Stack component="section" aria-label="Project storage" spacing={2}>
    <Typography variant="h6"><HelpLabel topic="storage">{project.display_name} storage</HelpLabel></Typography>
    {notice && <Alert severity="success">{notice}</Alert>}
    {error && <Alert severity="error" action={!open ? <Button onClick={() => setRevision((value) => value + 1)}>Retry storage</Button> : undefined}>{error}</Alert>}
    {!usage && !error && <CircularProgress aria-label="Measuring project storage" />}
    {usage && <>
      <Box component="dl" className="storage-metrics">
        <StorageMetric label="Working copies" value={count(usage.working_copies.directories, "folder")} detail={`${usage.working_copies.truncated ? "At least " : ""}${size(usage.working_copies.bytes)}`} description={scopes.worktrees.description} />
        <StorageMetric label="Saved reports and evidence" value={count(usage.artifacts, "file")} detail={size(usage.artifact_bytes)} description="Reports and changes retained from job attempts." />
        <StorageMetric label="Run history" value={count(usage.runs, "run")} description="Stored in the shared Relay database. Disk pages cannot be assigned to individual projects." />
        <StorageMetric label="Run references" value={`${usage.branches} ${usage.branches === 1 ? "branch" : "branches"}`} detail={count(usage.attempt_refs, "attempt ref")} description="Git objects share repository storage; their bytes cannot be counted separately." />
      </Box>
      {usage.working_copies.truncated && <Alert severity="info">The disk scan reached its limit or could not read a folder. The size is a lower bound; symlinks are excluded.</Alert>}
      {usage.cleanup_blocked && <Alert severity="info">Finish or cancel active project runs before deleting retained data.</Alert>}
      <HelpSelectField topic="storage" label="Data to delete" fullWidth value={scope} disabled={busy || usage.cleanup_blocked} onChange={(event) => { if (isScope(event.target.value)) setScope(event.target.value); }}>
        <MenuItem value="" disabled>Choose data to delete</MenuItem>{Object.entries(scopes).map(([key, value]) => <MenuItem key={key} value={key}>{value.label}</MenuItem>)}
      </HelpSelectField>
      {scope && <Typography>{scopes[scope].description}</Typography>}
      <Button sx={{ alignSelf: "flex-start" }} color="error" variant="outlined" disabled={!scope || usage.cleanup_blocked || busy} onClick={() => { setName(""); setOpen(true); }}>Review deletion</Button>
    </>}
    <TemporaryResourceCleanup key={`${project.id}:${revision}`} projectId={project.id} />
    <Dialog open={open} onClose={() => { if (!busy) setOpen(false); }} fullWidth aria-labelledby="storage-delete-title">
      <DialogTitle id="storage-delete-title">Delete retained data for {project.display_name}?</DialogTitle><DialogContent><Stack spacing={2}>
        <Typography>{scope ? scopes[scope].description : "Choose a deletion category."}</Typography>
        {usage && <Typography>{usage.runs} runs, {usage.artifacts} saved files ({size(usage.artifact_bytes)}), {usage.working_copies.directories} working copies, and {usage.branches} run branches are currently retained. Only the selected category is removed. Counts may change before confirmation.</Typography>}
        {scope === "all" && <TextField autoFocus label="Type the project name to confirm" value={name} onChange={(event) => setName(event.target.value)} helperText={project.display_name} disabled={busy} />}
        {error && <Alert severity="error">{error}</Alert>}
      </Stack></DialogContent><DialogActions><Button disabled={busy} onClick={() => setOpen(false)}>Cancel</Button><Button color="error" variant="contained" disabled={busy || (scope === "all" && name !== project.display_name)} onClick={() => void clean()}>{busy ? "Deleting…" : "Confirm deletion"}</Button></DialogActions>
    </Dialog>
  </Stack>;
}
