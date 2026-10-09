import { Alert, Box, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, Drawer, FormControlLabel, Menu, MenuItem, Paper, Stack, TextField, Typography } from "@mui/material";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api, csrfToken, errorMessage } from "../api";
import { projectPath } from "../navigation";
import { editorHolder } from "../editor-session";
import { actionsGraph, editorYaml, editActions, moveActionStep, launchView, parseActions, type ActionWorkflow } from "../actions-workflow";
import type { AgentRecord, AgentsResponse, ProjectSettingsResponse, ProviderDefaults, WorkflowDocumentResponse, WorkflowDraft } from "../types";
import type { WorkflowWorkspaceProps } from "./WorkflowWorkspace";
import { FlowCanvas } from "./FlowCanvas";
import { YamlEditor } from "./YamlEditor";
import { CreateWorkflowDialog } from "./CreateWorkflowDialog";
import { LaunchPanel } from "./LaunchPanel";
import { WorkflowSettings } from "./WorkflowSettings";
import { ActionJobEditor } from "./ActionJobEditor";
import { WorkflowSourceSettings } from "./WorkflowSourceSettings";
import type { LanguageManifest } from "../workflow-language";
import type { PromptEdits } from "./PromptFilesEditor";
import { useUndoDocument } from "../useUndoDocument";
import { formatWorkflowYaml, sourceDiff } from "../source-format";
import { WorkflowManagement } from "./WorkflowManagement";
import { WorkflowSidebar, type WorkflowEntry } from "./WorkflowSidebar";

type Diagnostic = { message: string; context?: { field?: string; line?: string; column?: string } };
type Trigger = { workflow_key: string; event: string; enabled: boolean };
const encoded = (key: string) => key.split("/").map(encodeURIComponent).join("/");

export function ActionsWorkflowWorkspace(props: WorkflowWorkspaceProps) {
  const [inventory, setInventory] = useState<WorkflowEntry[]>([]);
  const [key, setKey] = useState(props.initialWorkflow || "");
  const { text, setText, reset: resetUndo, undo, redo, canUndo, canRedo } = useUndoDocument(); const [saved, setSaved] = useState("");
  const [base, setBase] = useState(""); const [draft, setDraft] = useState<WorkflowDraft | null>(null);
  const [notice, setNotice] = useState("");
  const [agents, setAgents] = useState<AgentRecord[]>([]); const [defaultModel, setDefaultModel] = useState("");
  const [providerDefaults, setProviderDefaults] = useState<Record<string, ProviderDefaults>>({});
  const [loadedDocument, setLoadedDocument] = useState("");
  const [leaseError, setLeaseError] = useState("");
  const [lease, setLease] = useState(false); const [error, setError] = useState("");
  const [jobId, setJobId] = useState(""); const [search, setSearch] = useState(""); const [focusRequest, setFocusRequest] = useState(0); const [index, setIndex] = useState(0);
  const [create, setCreate] = useState(Boolean(props.initialCreate));
  const [launch, setLaunch] = useState(props.initialLaunch);
  const [diagnostics, setDiagnostics] = useState<Diagnostic[]>([]); const [valid, setValid] = useState(false);
  const [triggerRows, setTriggerRows] = useState<Trigger[]>([]); const [activation, setActivation] = useState<string | null>(null);
  const [authorize, setAuthorize] = useState(false);
  const [manifest, setManifest] = useState<LanguageManifest | null>(null);
  const [sourceSettings, setSourceSettings] = useState(false);
  const [promptEdits, setPromptEdits] = useState<PromptEdits>({});
  const [mode, setMode] = useState("Split");
  const [drawer, setDrawer] = useState(false); const [formatted, setFormatted] = useState<string | null>(null);
  const [contextMenu, setContextMenu] = useState<{ id: string; x: number; y: number } | null>(null);
  const [startJob, setStartJob] = useState("");
  const [newKind, setNewKind] = useState("script");
  const [settings, setSettings] = useState(false); const [environments, setEnvironments] = useState<string[]>([]);
  const holder = useRef(editorHolder()); const writes = useRef(Promise.resolve());
  const currentDocument = useRef("");
  const [lastValid, setLastValid] = useState<ActionWorkflow | null>(null);
  const parsed = useMemo(() => parseActions(text), [text]);
  const savedParsed = useMemo(() => parseActions(saved), [saved]);
  const graph = useMemo(() => actionsGraph(valid ? parsed.value : lastValid ?? parsed.value), [parsed.value, lastValid, valid]);
  useEffect(() => { if (valid && parsed.value) setLastValid(parsed.value); }, [valid, parsed.value]);
  const job = parsed.value?.jobs[jobId];
  const matchingJobs = Object.entries(parsed.value?.jobs || {}).filter(([id, item]) => `${id} ${item.name || ""}`.toLowerCase().includes(search.toLowerCase()));
  useEffect(() => {
    const abort = new AbortController();
    void Promise.all([api<AgentsResponse>("/api/agents", { signal: abort.signal }), api<ProjectSettingsResponse>(projectPath("/api/projects/defaults", props.requestProject), { signal: abort.signal })]).then(([inventory, defaults]) => { if (!abort.signal.aborted) { setAgents(inventory.agents); setDefaultModel(defaults.effective.workflow_defaults.model || ""); setProviderDefaults(defaults.effective.workflow_defaults.providers); } }).catch(e => { if (!abort.signal.aborted) setError(errorMessage(e)); });
    return () => abort.abort();
  }, [props.requestProject]);
  useEffect(() => { const abort = new AbortController(); void api<LanguageManifest>("/api/workflow-language", { signal: abort.signal }).then(setManifest).catch(e => { if (!abort.signal.aborted) setError(errorMessage(e)); }); return () => abort.abort(); }, []);
  const path = (suffix: string) => projectPath(`/api/workflows/${encoded(key)}${suffix}`, props.requestProject);
  currentDocument.current = path("");
  const refresh = useCallback(async (signal?: AbortSignal) => {
    const result = await api<{ workflows: WorkflowEntry[] }>(projectPath("/api/workflows", props.requestProject), { signal });
    if (signal?.aborted) return;
    setInventory(result.workflows);
    if (!key && result.workflows.length) setKey((result.workflows.find(item => item.key === "workflow.yaml") || result.workflows[0]).key);
  }, [props.requestProject, key]);
  useEffect(() => { const abort = new AbortController(); void refresh(abort.signal).catch(e => { if (!abort.signal.aborted) setError(errorMessage(e)); }); return () => abort.abort(); }, [refresh]);
  useEffect(() => { if (props.initialWorkflow) setKey(props.initialWorkflow); }, [props.initialWorkflow]);
  useEffect(() => { if (props.initialLaunch) setLaunch(true); }, [props.initialLaunch]);
  useEffect(() => {
    if (!key) return;
    const abort = new AbortController();
    let renew: number | undefined;
    setLease(false); setLeaseError(""); setError(""); setSearch(""); setNotice("");
    setText(""); setSaved(""); setDraft(null); setPromptEdits({}); setLoadedDocument(""); setLastValid(null);
    const endpoint = projectPath(`/api/workflows/${encoded(key)}`, props.requestProject);
    const leaseEndpoint = projectPath(`/api/workflows/${encoded(key)}/lease`, props.requestProject);
    async function acquire() {
      try {
        const result = await api<{ lease: unknown; conflict?: { message: string } }>(leaseEndpoint, { method: "POST", signal: abort.signal, body: JSON.stringify({ holder: holder.current, soft_conflict: true }) });
        if (!abort.signal.aborted) { setLease(Boolean(result.lease)); setLeaseError(result.conflict?.message ?? ""); }
      } catch (e) { if (!abort.signal.aborted) { setLease(false); setLeaseError(errorMessage(e)); } }
    }
    void api<WorkflowDocumentResponse>(endpoint, { signal: abort.signal }).then(async result => {
      if (abort.signal.aborted) return;
      setText(editorYaml(result.draft?.yaml ?? result.yaml)); setSaved(editorYaml(result.yaml)); setBase(result.base_hash); setDraft(result.draft); setPromptEdits(result.draft?.prompts ?? {}); setLoadedDocument(endpoint);
      await acquire();
      if (!abort.signal.aborted) { props.onWorkflowLoaded(key); renew = window.setInterval(() => { void acquire(); }, 30000); }
    }).catch(e => { if (!abort.signal.aborted) setError(errorMessage(e)); });
    const release = () => {
      navigator.sendBeacon(leaseEndpoint.replace(/\/lease(?=\?|$)/, "/lease/release"), new URLSearchParams({ holder: holder.current, csrfmiddlewaretoken: csrfToken() }));
    };
    window.addEventListener("pagehide", release);
    return () => { abort.abort(); window.clearInterval(renew); window.removeEventListener("pagehide", release); release(); };
  }, [key, props.requestProject]);
  const flush = useCallback(async () => {
    if (!key || loadedDocument !== projectPath(`/api/workflows/${encoded(key)}`, props.requestProject) || (text === (draft ? editorYaml(draft.yaml) : saved) && JSON.stringify(promptEdits) === JSON.stringify(draft?.prompts ?? {}))) return;
    if (!lease) throw new Error("The editing lease is unavailable. Your draft remains in this editor.");
    writes.current = writes.current.catch(() => undefined).then(async () => {
      const result = await api<{ draft: WorkflowDraft }>(projectPath(`/api/workflows/${encoded(key)}/draft`, props.requestProject), { method: "POST", body: JSON.stringify({ yaml: text, prompts: promptEdits, base_hash: base, holder: holder.current }) });
      if (currentDocument.current === loadedDocument) setDraft(result.draft);
    });
    await writes.current;
  }, [key, text, saved, draft, lease, base, props.requestProject, loadedDocument, promptEdits]);
  useLayoutEffect(() => { props.onNavigationReady(flush); return () => props.onNavigationReady(null); }, [flush, props.onNavigationReady]);
  useEffect(() => { const timer = window.setTimeout(() => { void flush().catch(e => { if (currentDocument.current === loadedDocument) setError(errorMessage(e)); }); }, 600); return () => window.clearTimeout(timer); }, [flush]);
  useEffect(() => {
    setValid(false); setDiagnostics([]); if (!text || loadedDocument !== path("")) return;
    const abort = new AbortController(); const timer = window.setTimeout(() => {
      void api<{ valid: boolean; diagnostics: Diagnostic[] }>(projectPath("/api/workflow-language/validate", props.requestProject), { method: "POST", signal: abort.signal, body: JSON.stringify({ yaml: text, source: key }) }).then(result => { if (!abort.signal.aborted) { setValid(result.valid); setDiagnostics(result.diagnostics); } }).catch(e => { if (!abort.signal.aborted) setError(errorMessage(e)); });
    }, 300);
    return () => { abort.abort(); window.clearTimeout(timer); };
  }, [text, key, props.requestProject, loadedDocument]);
  useEffect(() => { setJobId(current => parsed.value?.jobs[current] ? current : Object.keys(parsed.value?.jobs || {})[0] || ""); }, [parsed.value]);
  useEffect(() => { setIndex(0); }, [jobId]);
  useEffect(() => { const abort = new AbortController(); setTriggerRows([]); void api<{ triggers: Trigger[] }>(projectPath("/api/workflow-triggers", props.requestProject), { signal: abort.signal }).then(result => { if (!abort.signal.aborted) setTriggerRows(result.triggers); }).catch(e => { if (!abort.signal.aborted) setError(errorMessage(e)); }); return () => abort.abort(); }, [props.requestProject]);
  async function save(next = text): Promise<boolean> {
    const target = path("");
    try { await flush(); await api(path("/save"), { method: "POST", body: JSON.stringify({ yaml: next, prompts: promptEdits, base_hash: base, holder: holder.current }) });
      const result = await api<WorkflowDocumentResponse>(target); if (currentDocument.current !== target) return false; setText(editorYaml(result.yaml)); setSaved(editorYaml(result.yaml)); setBase(result.base_hash); setDraft(null); setPromptEdits({}); setError(""); setNotice("Workflow and instructions saved and validated."); return true;
    } catch (e) { if (currentDocument.current === target) setError(errorMessage(e)); return false; }
  }
  async function restoreSaved() {
    const target = path("");
    const previousDraft = draft;
    setText(saved); setPromptEdits({});
    try { if (previousDraft) await api(path("/draft/discard"), { method: "POST", body: JSON.stringify({ updated_at: previousDraft.updated_at }) }); if (currentDocument.current === target) { setDraft(null); setError(""); } }
    catch (e) { if (currentDocument.current === target) setError(errorMessage(e)); }
  }
  async function takeOver() {
    try { await api(path("/lease"), { method: "POST", body: JSON.stringify({ holder: holder.current, takeover: true }) }); setLease(true); setLeaseError(""); }
    catch (e) { setError(errorMessage(e)); }
  }
  useEffect(() => {
    function shortcut(event: KeyboardEvent) { if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z" && !(event.target instanceof HTMLElement && event.target.closest("input, textarea, .cm-content"))) { event.preventDefault(); if (event.shiftKey) redo(); else undo(); } if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "s") { event.preventDefault(); if (lease && valid) void save(); } }
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  });
  useEffect(() => { const abort = new AbortController(); setEnvironments([]); void api<{ environments: Array<{ name: string }> }>(projectPath("/api/workflow-environments", props.requestProject), { signal: abort.signal }).then(result => { if (!abort.signal.aborted) setEnvironments(result.environments.map(item => item.name)); }).catch(e => { if (!abort.signal.aborted) setError(errorMessage(e)); }); return () => abort.abort(); }, [props.requestProject]);
  function change(parts: Array<string | number>, value: unknown) { try { setText(editActions(text, parts, value)); } catch (e) { setError(errorMessage(e)); } }
  async function toggleTrigger(event: string, enabled: boolean) {
    try { const result = await api<{ triggers: Trigger[] }>(projectPath("/api/workflow-triggers", props.requestProject), { method: "POST", body: JSON.stringify({ key, event, enabled, allow_writers: enabled }) }); setTriggerRows(result.triggers); setActivation(null); setAuthorize(false); } catch (e) { setError(errorMessage(e)); }
  }
  const events = parsed.value?.on && typeof parsed.value.on === "object" && !Array.isArray(parsed.value.on) ? Object.keys(parsed.value.on) : typeof parsed.value?.on === "string" ? [parsed.value.on] : [];
  useEffect(resetUndo, [base, key, resetUndo]);
  function removeJob(id: string) {
    let next = editActions(text, ["jobs", id], undefined);
    for (const [other, value] of Object.entries(parsed.value?.jobs ?? {})) {
      const needs = typeof value.needs === "string" ? [value.needs] : value.needs ?? [];
      if (other !== id && needs.includes(id)) next = editActions(next, ["jobs", other, "needs"], needs.filter(item => item !== id));
    }
    setText(next); setContextMenu(null); setDrawer(false);
  }
  function addJob(source?: string, target?: string) {
    let number = 1; while (parsed.value?.jobs[`job_${number}`]) number++;
    const id = `job_${number}`;
    const step = newKind === "script" ? { run: "echo Ready" } : { uses: newKind, with: Object.fromEntries((manifest?.builtin_inputs[newKind]?.required ?? []).map(field => [field, field === "max-iterations" ? "3" : ""])) };
    let next = editActions(text, ["jobs", id], { ...(source ? { needs: [source] } : {}), steps: [step] });
    if (target) { const job = parsed.value?.jobs[target]; const needs = typeof job?.needs === "string" ? [job.needs] : job?.needs ?? []; next = editActions(next, ["jobs", target, "needs"], [...needs.filter(item => item !== source), id]); }
    setText(next); setJobId(id); setDrawer(true);
  }
  async function runFromJob(id: string) {
    const point = `root.${id}`; const entries = parsed.value?.entrypoints ?? [];
    const next = entries.some(entry => entry.scope_path === point) ? text : editActions(text, ["entrypoints"], [...entries, { scope_path: point }]);
    setContextMenu(null); setText(next);
    if (await save(next)) { setStartJob(point); setLaunch(true); }
  }
  function duplicateJob(id: string) {
    let next = `${id}_copy`; let number = 2; while (parsed.value?.jobs[next]) next = `${id}_copy_${number++}`;
    change(["jobs", next], parsed.value?.jobs[id]); setJobId(next); setContextMenu(null); setDrawer(true);
  }
  const disabled = inventory.find(item => item.key === key)?.disabled === true;
  return <Box className="actions-layout">
    <WorkflowSidebar workflows={inventory} selected={key} project={props.project.id} editor onCreate={() => setCreate(true)} onSelect={next => { if (!next) { window.location.assign(`/?view=runs&project=${encodeURIComponent(props.project.id)}`); return; } void flush().then(() => setKey(next)).catch(e => setError(errorMessage(e))); }} />
    <Stack spacing={2} className="actions-main">
    <Stack component="section" aria-label="Workflow header" direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1 }}><Typography component="h1" variant="h5" sx={{ flex: "1 1 100%", overflowWrap: "anywhere" }}>{parsed.value?.name || inventory.find(item => item.key === key)?.name || "Choose a workflow"}</Typography><TextField select label="Workflow" value={key} onChange={async event => { try { await flush(); setKey(event.target.value); } catch(e) { setError(errorMessage(e)); } }} sx={{ minWidth: 220 }}>{inventory.map(item => <MenuItem key={item.key} value={item.key}>{item.name || item.key}</MenuItem>)}</TextField>
      <Button onClick={() => setCreate(true)}>Create workflow</Button><Button onClick={() => void save()} disabled={!lease || !valid || (text === saved && !Object.keys(promptEdits).length)}>Save</Button>{!disabled && <Button variant="contained" onClick={() => setLaunch(true)} disabled={!savedParsed.value}>Run workflow</Button>}
      <WorkflowManagement workflowKey={key} name={parsed.value?.name || key} baseHash={base} holder={holder.current} project={props.requestProject} disabled={disabled} onChanged={async next => { const result = await api<{ workflows: WorkflowEntry[] }>(projectPath("/api/workflows", props.requestProject)); setInventory(result.workflows); setKey(next ?? result.workflows[0]?.key ?? ""); if (next === key) setNotice("Workflow availability updated."); }} /></Stack>
    {disabled && <Alert severity="info">This workflow is disabled. Enable it to run again.</Alert>}
    <Button disabled={!parsed.value} onClick={() => setSourceSettings(true)}>Workflow settings</Button>
    <WorkflowSourceSettings open={sourceSettings} value={parsed.value} manifest={manifest} change={change} onClose={() => setSourceSettings(false)} />
    <TextField select label="Editor mode" value={mode} onChange={event => setMode(event.target.value)}>{["Visual", "YAML", "Split"].map(item => <MenuItem value={item} key={item}>{item}</MenuItem>)}</TextField>
    <Stack direction="row" spacing={1}><Button disabled={!canUndo} onClick={undo}>Undo</Button><Button disabled={!canRedo} onClick={redo}>Redo</Button><Button disabled={!parsed.value} onClick={() => { try { setFormatted(formatWorkflowYaml(text)); } catch (e) { setError(errorMessage(e)); } }}>Format as YAML</Button></Stack>
    {(text !== saved || Object.keys(promptEdits).length > 0) && <Alert severity="info" action={<Button onClick={() => void restoreSaved()}>Discard changes</Button>}>Unsaved changes: {[text !== saved ? key : "", ...Object.keys(promptEdits)].filter(Boolean).join(", ")}</Alert>}
    <Button onClick={() => setSettings(true)}>Variables, secrets, environments and library</Button>
    <WorkflowSettings open={settings} projectId={props.requestProject || props.project.id} yaml={text} onClose={() => setSettings(false)} onEnvironments={setEnvironments} />
    {lease && valid && <Typography>Ready to edit</Typography>}
    {notice && <Alert severity="success">{notice}</Alert>}
    {!key && <Typography variant="h6">No workflows yet</Typography>}
    {leaseError && <Alert severity="info" action={<Button onClick={() => void takeOver()}>Edit here instead</Button>}>{leaseError}</Alert>}{error && <Alert severity="error">{error}</Alert>}{(draft || text !== saved) && saved && <Alert severity="info">Your unsaved draft is not included when you run the saved workflow.<Button onClick={() => void restoreSaved()}>Restore saved source</Button><Box component="details"><Box component="summary">Compare draft with saved source</Box><Typography component="pre" sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>Saved source:{"\n"}{saved}{"\n"}Draft:{"\n"}{text}</Typography></Box></Alert>}
    {diagnostics.map((item, i) => <Alert severity="error" key={i} action={item.context?.field?.match(/^jobs\.([^.[]+)/) ? <Button onClick={() => { setJobId(item.context!.field!.match(/^jobs\.([^.[]+)/)![1]); setDrawer(true); }}>Open job</Button> : undefined}>{item.context?.line ? `Line ${item.context.line}: ` : ""}{item.message}</Alert>)}
    <Box sx={{ display: "grid", gridTemplateColumns: { xs: "minmax(0, 1fr)", lg: mode === "Split" ? "minmax(0, 1fr) minmax(0, 1fr)" : "minmax(0, 1fr)" }, gap: 2 }}>
      {mode !== "YAML" && <Paper sx={{ p: 2 }}><Stack spacing={2}><Typography component="h2" variant="h6">Jobs and ordered steps</Typography>{!valid && lastValid && <Alert severity="info">Showing the last valid version</Alert>}<Box sx={{ opacity: !valid && lastValid ? .6 : 1 }}><FlowCanvas key={key} focusRequest={focusRequest} selectedId={jobId || undefined} initialFocusId={graph.nodes[0]?.id} followSelection nodes={graph.nodes} edges={graph.edges.map(edge => ({ ...edge, type: "insertJob", data: { onInsert: addJob } }))} onSelect={id => { setJobId(id); setDrawer(true); }} onContextMenu={(id, x, y) => setContextMenu({ id, x, y })} onConnect={connection => { if (!connection.source || !connection.target || connection.source === connection.target) return; const job = parsed.value?.jobs[connection.target]; const needs = typeof job?.needs === "string" ? [job.needs] : job?.needs ?? []; change(["jobs", connection.target, "needs"], [...new Set([...needs, connection.source])]); }} onDeleteEdges={edges => { let next = text; for (const edge of edges) { const job = parseActions(next).value?.jobs[edge.target]; const needs = typeof job?.needs === "string" ? [job.needs] : job?.needs ?? []; next = editActions(next, ["jobs", edge.target, "needs"], needs.filter(item => item !== edge.source)); } setText(next); }} /></Box>
        <Stack component="nav" aria-label="Workflow job navigation"><TextField disabled={!parsed.value} label="Find a job" value={search} onChange={e => setSearch(e.target.value)} />{matchingJobs.map(([id, item]) => <Button key={id} aria-pressed={jobId === id} onClick={() => { setJobId(id); setDrawer(true); setFocusRequest(value => value + 1); }}>{item.name || id.replace(/_/g, " ").replace(/^./, letter => letter.toUpperCase())}</Button>)}{!matchingJobs.length && search && <Typography>No jobs match. Try another name.</Typography>}</Stack>
        <TextField select label="New job type" value={newKind} onChange={event => setNewKind(event.target.value)}><MenuItem value="script">Run a script</MenuItem>{manifest?.builtins.map(kind => <MenuItem value={kind} key={kind}>{kind.replace("relay/", "").replace("@v1", "")}</MenuItem>)}</TextField><Button disabled={!parsed.value} onClick={() => addJob()}>Add job</Button>
        </Stack></Paper>}
      {mode !== "Visual" && <Paper sx={{ p: 2 }}><Typography component="h2" variant="h6">Workflow YAML</Typography><YamlEditor value={text} onChange={setText} manifest={manifest} diagnostics={diagnostics} />
        {events.filter(event => ["schedule", "push", "workflow_run", "repository_dispatch"].includes(event)).map(event => { const enabled = triggerRows.some(row => row.workflow_key === key && row.event === event && row.enabled); return <Button key={event} onClick={() => enabled ? void toggleTrigger(event, false) : setActivation(event)}>{enabled ? "Disable" : "Activate"} {event}</Button>; })}</Paper>}
    </Box>
    <Drawer anchor="right" open={drawer && Boolean(job)} onClose={() => setDrawer(false)} slotProps={{ paper: { sx: { width: { xs: "100%", sm: 520 }, maxWidth: "100vw", p: 2 } } }}><Stack spacing={2}><Typography component="h2" variant="h6">Job settings</Typography><Stack direction="row"><Button onClick={() => setDrawer(false)}>Close job settings</Button><Button onClick={() => removeJob(jobId)}>Remove job</Button></Stack>{job && parsed.value && manifest && <ActionJobEditor workflow={parsed.value} jobId={jobId} index={index} onIndex={setIndex} manifest={manifest} change={change} onMove={(from, to) => { setText(moveActionStep(text, jobId, from, to)); setIndex(to); }} agents={agents} defaults={providerDefaults} defaultModel={defaultModel} project={props.requestProject} workflowKey={key} edits={promptEdits} onEdits={(reference, edit) => setPromptEdits(current => ({ ...current, [reference]: edit }))} />}</Stack></Drawer>
    <Menu open={Boolean(contextMenu)} onClose={() => setContextMenu(null)} anchorReference="anchorPosition" anchorPosition={contextMenu ? { left: contextMenu.x, top: contextMenu.y } : undefined}><MenuItem onClick={() => { if (contextMenu) duplicateJob(contextMenu.id); }}>Duplicate job</MenuItem><MenuItem onClick={() => { if (contextMenu) removeJob(contextMenu.id); }}>Delete job</MenuItem><MenuItem onClick={() => { if (contextMenu) void runFromJob(contextMenu.id); }}>Run from here</MenuItem></Menu>
    <Dialog open={formatted !== null} onClose={() => setFormatted(null)} fullWidth maxWidth="md"><DialogTitle>Preview YAML formatting</DialogTitle><DialogContent><Box component="pre" sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{sourceDiff(text, formatted ?? text)}</Box></DialogContent><DialogActions><Button onClick={() => setFormatted(null)}>Cancel</Button><Button onClick={() => { if (formatted !== null) setText(formatted); setFormatted(null); }}>Apply formatting</Button></DialogActions></Dialog>
    <CreateWorkflowDialog holder={holder.current} open={create} requestProject={props.requestProject} onClose={() => setCreate(false)} onCreated={async newKey => { setCreate(false); setKey(newKey); await refresh(); }} />
    <LaunchPanel initialEntryPoint={startJob} open={launch} workflowKey={key} workflow={launchView(savedParsed.value, environments)} project={props.project} requestProject={props.requestProject} modelOptions={[]} blockedReason={!savedParsed.value ? "Choose a valid saved workflow." : null} saveError={null} draftNotice={text !== saved || Object.keys(promptEdits).length ? "Your unsaved draft is not included. This runs the saved workflow." : null} onClose={() => { setLaunch(false); props.onLaunchClosed(); }} onExited={() => undefined} onRunLaunched={props.onRunLaunched} previousRun={null} />
    <Dialog open={Boolean(activation)} onClose={() => { setActivation(null); setAuthorize(false); }}><DialogTitle>Activate {activation}</DialogTitle><DialogContent><FormControlLabel control={<Checkbox checked={authorize} onChange={e => setAuthorize(e.target.checked)} />} label="Allow this trigger to launch writing jobs automatically on this computer." /></DialogContent><DialogActions><Button onClick={() => setActivation(null)}>Cancel</Button><Button disabled={!authorize || text !== saved} onClick={() => { if (activation) void toggleTrigger(activation, true); }}>Activate trigger</Button></DialogActions></Dialog>
  </Stack></Box>;
}
