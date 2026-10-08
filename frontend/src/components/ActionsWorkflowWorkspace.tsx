import { Alert, Box, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Paper, Stack, TextField, Typography } from "@mui/material";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { api, errorMessage } from "../api";
import { projectPath } from "../navigation";
import { editorHolder } from "../editor-session";
import { actionsGraph, editActions, moveActionStep, launchView, parseActions, type ActionStep } from "../actions-workflow";
import type { AgentRecord, AgentsResponse, ProjectSettingsResponse, ProviderDefaults, WorkflowDocumentResponse, WorkflowDraft } from "../types";
import type { WorkflowWorkspaceProps } from "./WorkflowWorkspace";
import { FlowCanvas } from "./FlowCanvas";
import { YamlEditor } from "./YamlEditor";
import { CreateWorkflowDialog } from "./CreateWorkflowDialog";
import { LaunchPanel } from "./LaunchPanel";
import { WorkflowSettings } from "./WorkflowSettings";
import { AgentConfiguration } from "./AgentConfiguration";

type Diagnostic = { message: string; context?: { field?: string; line?: string; column?: string } };
type Trigger = { workflow_key: string; event: string; enabled: boolean };
const encoded = (key: string) => key.split("/").map(encodeURIComponent).join("/");

export function ActionsWorkflowWorkspace(props: WorkflowWorkspaceProps) {
  const [inventory, setInventory] = useState<Array<{ key: string; name: string }>>([]);
  const [key, setKey] = useState(props.initialWorkflow || "");
  const [text, setText] = useState(""); const [saved, setSaved] = useState("");
  const [base, setBase] = useState(""); const [draft, setDraft] = useState<WorkflowDraft | null>(null);
  const [notice, setNotice] = useState("");
  const [agents, setAgents] = useState<AgentRecord[]>([]); const [defaultModel, setDefaultModel] = useState("");
  const [providerDefaults, setProviderDefaults] = useState<Record<string, ProviderDefaults>>({});
  const [lease, setLease] = useState(false); const [error, setError] = useState("");
  const [jobId, setJobId] = useState(""); const [search, setSearch] = useState(""); const [focusRequest, setFocusRequest] = useState(0); const [index, setIndex] = useState(0);
  const [create, setCreate] = useState(Boolean(props.initialCreate));
  const [launch, setLaunch] = useState(props.initialLaunch);
  const [diagnostics, setDiagnostics] = useState<Diagnostic[]>([]); const [valid, setValid] = useState(false);
  const [conversion, setConversion] = useState<{ yaml: string; issues: string[]; complete: boolean } | null>(null);
  const [triggerRows, setTriggerRows] = useState<Trigger[]>([]); const [activation, setActivation] = useState<string | null>(null);
  const [authorize, setAuthorize] = useState(false);
  const [settings, setSettings] = useState(false); const [environments, setEnvironments] = useState<string[]>([]);
  const holder = useRef(editorHolder()); const writes = useRef(Promise.resolve());
  const parsed = useMemo(() => parseActions(text), [text]); const graph = useMemo(() => actionsGraph(parsed.value), [parsed.value]);
  const job = parsed.value?.jobs[jobId]; const step = job?.steps?.[index];
  const matchingJobs = Object.entries(parsed.value?.jobs || {}).filter(([id, item]) => `${id} ${item.name || ""}`.toLowerCase().includes(search.toLowerCase()));
  const withInput = (field: string, value: string) => change(["jobs", jobId, "steps", index, "with", field], value || undefined);
  let agentId = String(step?.with?.agent || "");
  if (!agentId) { try { const ordered = JSON.parse(String(step?.with?.agents || "[]")); agentId = Array.isArray(ordered) ? String(ordered[0] || "") : ""; } catch { /* Server validation reports invalid arrays. */ } }
  const selectedAgent = agents.find(item => item.id === agentId);
  const model = String(step?.with?.model || providerDefaults[agentId]?.model || defaultModel);
  useEffect(() => {
    const abort = new AbortController();
    void Promise.all([api<AgentsResponse>("/api/agents", { signal: abort.signal }), api<ProjectSettingsResponse>(projectPath("/api/projects/defaults", props.requestProject), { signal: abort.signal })]).then(([inventory, defaults]) => { if (!abort.signal.aborted) { setAgents(inventory.agents); setDefaultModel(defaults.effective.workflow_defaults.model || ""); setProviderDefaults(defaults.effective.workflow_defaults.providers); } }).catch(e => { if (!abort.signal.aborted) setError(errorMessage(e)); });
    return () => abort.abort();
  }, [props.requestProject]);
  const path = (suffix: string) => projectPath(`/api/workflows/${encoded(key)}${suffix}`, props.requestProject);
  const refresh = useCallback(async () => {
    const result = await api<{ workflows: Array<{ key: string; name: string }> }>(projectPath("/api/workflows", props.requestProject));
    setInventory(result.workflows);
    if (!key && result.workflows.length) setKey((result.workflows.find(item => item.key === "workflow.yaml") || result.workflows[0]).key);
  }, [props.requestProject, key]);
  useEffect(() => { void refresh().catch(e => setError(errorMessage(e))); }, [refresh]);
  useEffect(() => { if (props.initialWorkflow) setKey(props.initialWorkflow); }, [props.initialWorkflow]);
  useEffect(() => { if (props.initialLaunch) setLaunch(true); }, [props.initialLaunch]);
  useEffect(() => {
    if (!key) return;
    const abort = new AbortController(); setLease(false); setError(""); setSearch("");
    const endpoint = projectPath(`/api/workflows/${encoded(key)}`, props.requestProject);
    void api<WorkflowDocumentResponse>(endpoint, { signal: abort.signal }).then(async result => {
      if (abort.signal.aborted) return;
      setText(result.draft?.yaml || result.yaml); setSaved(result.yaml); setBase(result.base_hash); setDraft(result.draft);
      const acquired = await api<{ acquired?: boolean }>(`${endpoint}/lease`, { method: "POST", body: JSON.stringify({ holder: holder.current }) });
      if (!abort.signal.aborted) { setLease(acquired.acquired !== false); props.onWorkflowLoaded(key); }
    }).catch(e => { if (!abort.signal.aborted) setError(errorMessage(e)); });
    const renew = window.setInterval(() => { void api(`${endpoint}/lease`, { method: "POST", body: JSON.stringify({ holder: holder.current }) }).catch(e => { setLease(false); setError(errorMessage(e)); }); }, 30000);
    return () => { abort.abort(); window.clearInterval(renew); };
  }, [key, props.requestProject]);
  const flush = useCallback(async () => {
    if (!key || text === (draft?.yaml || saved)) return;
    if (!lease) throw new Error("The editing lease is unavailable. Your draft remains in this editor.");
    writes.current = writes.current.catch(() => undefined).then(async () => {
      const result = await api<{ draft: WorkflowDraft }>(projectPath(`/api/workflows/${encoded(key)}/draft`, props.requestProject), { method: "POST", body: JSON.stringify({ yaml: text, base_hash: base, holder: holder.current }) });
      setDraft(result.draft);
    });
    await writes.current;
  }, [key, text, saved, draft, lease, base, props.requestProject]);
  useLayoutEffect(() => { props.onNavigationReady(flush); return () => props.onNavigationReady(null); }, [flush, props.onNavigationReady]);
  useEffect(() => { const timer = window.setTimeout(() => { void flush().catch(e => setError(errorMessage(e))); }, 600); return () => window.clearTimeout(timer); }, [flush]);
  useEffect(() => {
    setValid(false); if (!text) return;
    const abort = new AbortController(); const timer = window.setTimeout(() => {
      void api<{ valid: boolean; diagnostics: Diagnostic[] }>(projectPath("/api/workflow-language/validate", props.requestProject), { method: "POST", signal: abort.signal, body: JSON.stringify({ yaml: text, source: key }) }).then(result => { if (!abort.signal.aborted) { setValid(result.valid); setDiagnostics(result.diagnostics); } }).catch(e => { if (!abort.signal.aborted) setError(errorMessage(e)); });
    }, 300);
    return () => { abort.abort(); window.clearTimeout(timer); };
  }, [text, key, props.requestProject]);
  useEffect(() => { setJobId(current => parsed.value?.jobs[current] ? current : Object.keys(parsed.value?.jobs || {})[0] || ""); }, [parsed.value]);
  useEffect(() => { setIndex(0); }, [jobId]);
  useEffect(() => { void api<{ triggers: Trigger[] }>(projectPath("/api/workflow-triggers", props.requestProject)).then(result => setTriggerRows(result.triggers)).catch(e => setError(errorMessage(e))); }, [props.requestProject]);
  async function save() {
    try { await flush(); await api(path("/save"), { method: "POST", body: JSON.stringify({ yaml: text, base_hash: base, holder: holder.current }) });
      const result = await api<WorkflowDocumentResponse>(path("")); setSaved(result.yaml); setBase(result.base_hash); setDraft(null); setError(""); setNotice("Workflow saved and validated.");
    } catch (e) { setError(errorMessage(e)); }
  }
  useEffect(() => { void api<{ environments: Array<{ name: string }> }>(projectPath("/api/workflow-environments", props.requestProject)).then(result => setEnvironments(result.environments.map(item => item.name))).catch(e => setError(errorMessage(e))); }, [props.requestProject]);
  function change(parts: Array<string | number>, value: unknown) { try { setText(editActions(text, parts, value)); } catch (e) { setError(errorMessage(e)); } }
  const editStep = (field: keyof ActionStep, value: unknown) => change(["jobs", jobId, "steps", index, field], value === "" ? undefined : value);
  function jsonField(label: string, parts: Array<string | number>, value: unknown) {
    return <TextField key={parts.join(".") + JSON.stringify(value)} label={label} multiline minRows={2} defaultValue={JSON.stringify(value ?? {}, null, 2)} onBlur={event => { try { change(parts, JSON.parse(event.target.value)); } catch (e) { setError(errorMessage(e)); } }} helperText="JSON values; YAML comments and unrelated fields are preserved." />;
  }
  async function toggleTrigger(event: string, enabled: boolean) {
    try { const result = await api<{ triggers: Trigger[] }>(projectPath("/api/workflow-triggers", props.requestProject), { method: "POST", body: JSON.stringify({ key, event, enabled, allow_writers: enabled }) }); setTriggerRows(result.triggers); setActivation(null); setAuthorize(false); } catch (e) { setError(errorMessage(e)); }
  }
  const events = parsed.value?.on && typeof parsed.value.on === "object" && !Array.isArray(parsed.value.on) ? Object.keys(parsed.value.on) : typeof parsed.value?.on === "string" ? [parsed.value.on] : [];
  return <Stack spacing={2}>
    <Stack component="section" aria-label="Workflow header" direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1 }}><Typography variant="h5" sx={{ flex: "1 1 100%", overflowWrap: "anywhere" }}>{parsed.value?.name || inventory.find(item => item.key === key)?.name || "Choose a workflow"}</Typography><TextField select label="Workflow" value={key} onChange={async event => { try { await flush(); setKey(event.target.value); } catch(e) { setError(errorMessage(e)); } }} sx={{ minWidth: 220 }}>{inventory.map(item => <MenuItem key={item.key} value={item.key}>{item.name || item.key}</MenuItem>)}</TextField>
      <Button onClick={() => setCreate(true)}>Create workflow</Button><Button onClick={() => void save()} disabled={!lease || !valid || text === saved}>Save</Button><Button variant="contained" onClick={() => setLaunch(true)} disabled={!valid || text !== saved}>Run workflow</Button></Stack>
    <Button onClick={() => setSettings(true)}>Variables, secrets, environments and library</Button>
    <WorkflowSettings open={settings} projectId={props.requestProject || props.project.id} yaml={text} onClose={() => setSettings(false)} onEnvironments={setEnvironments} />
    {lease && valid && <Typography>Ready to edit</Typography>}
    {notice && <Alert severity="success">{notice}</Alert>}
    {!key && <Typography variant="h6">No workflows yet</Typography>}
    {error && <Alert severity="error">{error}</Alert>}{draft && <Alert severity="info">Recovered draft loaded. Saving publishes the validated source.<Button onClick={() => { setText(saved); void api(path("/draft"), { method: "POST", body: JSON.stringify({ yaml: saved, base_hash: base, holder: holder.current }) }).then(() => setDraft(null)).catch(e => setError(errorMessage(e))); }}>Restore saved source</Button></Alert>}
    {diagnostics.map((item, i) => <Alert severity="error" key={i}>{item.context?.line ? `Line ${item.context.line}: ` : ""}{item.message}</Alert>)}
    {!parsed.value && text && <Button onClick={() => { void api<typeof conversion>(projectPath("/api/workflow-language/convert", props.requestProject), { method: "POST", body: JSON.stringify({ yaml: text }) }).then(setConversion).catch(e => setError(errorMessage(e))); }}>Preview legacy conversion</Button>}
    <Box sx={{ display: "grid", gridTemplateColumns: { xs: "minmax(0, 1fr)", lg: "minmax(0, 1fr) minmax(0, 1fr)" }, gap: 2 }}>
      <Paper sx={{ p: 2 }}><Stack spacing={2}><Typography variant="h6">Jobs and ordered steps</Typography><FlowCanvas key={key} focusRequest={focusRequest} selectedId={jobId} initialFocusId={Object.keys(parsed.value?.jobs || {})[0]} followSelection nodes={graph.nodes} edges={graph.edges} onSelect={setJobId} />
        <Stack component="nav" aria-label="Workflow job navigation"><TextField label="Find a job" value={search} onChange={e => setSearch(e.target.value)} />{matchingJobs.map(([id, item]) => <Button key={id} aria-pressed={jobId === id} onClick={() => { setJobId(id); setFocusRequest(value => value + 1); }}>{item.name || id.replace(/_/g, " ").replace(/^./, letter => letter.toUpperCase())}</Button>)}{!matchingJobs.length && search && <Typography>No jobs match. Try another name.</Typography>}</Stack>
        <Button onClick={() => { let number = 1; while (parsed.value?.jobs[`job_${number}`]) number++; const id = `job_${number}`; change(["jobs", id], { "runs-on": "self-hosted", steps: [{ run: "echo Ready" }] }); setJobId(id); }}>Add job</Button>
        {job && <><Button onClick={() => change(["jobs", jobId], undefined)}>Remove job</Button><TextField label="Job name" value={job.name || ""} onChange={e => change(["jobs", jobId, "name"], e.target.value)} /><TextField label="Needs (comma separated)" value={typeof job.needs === "string" ? job.needs : (job.needs || []).join(", ")} onChange={e => change(["jobs", jobId, "needs"], e.target.value.split(",").map(x => x.trim()).filter(Boolean))} />
          <TextField label="Job timeout (minutes)" value={job["timeout-minutes"] ?? ""} onChange={e => change(["jobs", jobId, "timeout-minutes"], e.target.value ? Number(e.target.value) : undefined)} /><FormControlLabel control={<Checkbox checked={job["continue-on-error"] === true} onChange={e => change(["jobs", jobId, "continue-on-error"], e.target.checked)} />} label="Continue after this job fails" /><TextField select label="Cache mode" value={job["cache-mode"] || "write"} onChange={e => change(["jobs", jobId, "cache-mode"], e.target.value)}>{["write", "read", "write-only", "none"].map(mode => <MenuItem value={mode} key={mode}>{mode}</MenuItem>)}</TextField><TextField label="Job condition" value={job.if || ""} onChange={e => change(["jobs", jobId, "if"], e.target.value || undefined)} />
          <TextField label="Reusable workflow" value={job.uses || ""} onChange={e => { if (e.target.value) { change(["jobs", jobId], { ...job, uses: e.target.value, steps: undefined, "runs-on": undefined }); } else change(["jobs", jobId, "uses"], undefined); }} />
          {jsonField("Matrix and strategy", ["jobs", jobId, "strategy"], job.strategy)}{jsonField("Job outputs", ["jobs", jobId, "outputs"], job.outputs)}{jsonField("Environment", ["jobs", jobId, "environment"], job.environment)}{jsonField("Concurrency", ["jobs", jobId, "concurrency"], job.concurrency)}
          {job.uses ? jsonField("Reusable inputs", ["jobs", jobId, "with"], job.with) : <><TextField select label="Ordered step" value={Math.min(index, (job.steps?.length || 1) - 1)} onChange={e => setIndex(Number(e.target.value))}>{job.steps?.map((item, i) => <MenuItem key={i} value={i}>{i + 1}. {item.name || item.id || item.uses || "Run script"}</MenuItem>)}</TextField>
          {step && <><TextField label="Step ID" value={step.id || ""} onChange={e => editStep("id", e.target.value)} /><TextField label="Step name" value={step.name || ""} onChange={e => editStep("name", e.target.value)} /><TextField label="Action reference" value={step.uses || ""} onChange={e => { change(["jobs", jobId, "steps", index], e.target.value ? { ...step, uses: e.target.value, run: undefined } : { ...step, uses: undefined, run: "echo Ready" }); }} />
            {step.uses === "relay/agent@v1" && <><TextField select label="Agent" value={agentId} onChange={e => { change(["jobs", jobId, "steps", index, "with"], { ...step.with, agent: e.target.value, agents: undefined, effort: undefined }); }}>{agents.map(item => <MenuItem key={item.id} value={item.id}>{item.display_name}</MenuItem>)}</TextField><TextField label="Exact model override" value={String(step.with?.model || "")} onChange={e => change(["jobs", jobId, "steps", index, "with"], { ...step.with, model: e.target.value || undefined, effort: undefined })} placeholder={defaultModel || "Use the saved default"} /><TextField label="Prompt files (one per line)" multiline value={String(step.with?.["prompt-files"] || "")} onChange={e => withInput("prompt-files", e.target.value)} /><TextField label="Agent prompt" multiline value={String(step.with?.prompt || "")} onChange={e => withInput("prompt", e.target.value)} />{selectedAgent && !model.includes("${{") && <AgentConfiguration agent={selectedAgent} model={model} inheritDefaults={providerDefaults[agentId]?.model === model} options={typeof step.with?.effort === "string" || step.with?.effort === null ? { effort: step.with.effort } : {}} fields={["effort"]} onChange={(_, value) => change(["jobs", jobId, "steps", index, "with", "effort"], value === "" ? undefined : value)} project={props.requestProject} />}</>}
            {step.uses ? jsonField("Action inputs", ["jobs", jobId, "steps", index, "with"], step.with) : <><TextField label="Script" multiline minRows={3} value={step.run || ""} onChange={e => editStep("run", e.target.value)} /><TextField label="Shell" value={step.shell || ""} onChange={e => editStep("shell", e.target.value)} /><TextField label="Working directory" value={step["working-directory"] || ""} onChange={e => editStep("working-directory", e.target.value)} /></>}
            <TextField label="Step condition" value={step.if || ""} onChange={e => editStep("if", e.target.value)} /><TextField label="Timeout (minutes or expression)" value={step["timeout-minutes"] ?? ""} onChange={e => editStep("timeout-minutes", e.target.value.includes("${{") ? e.target.value : e.target.value ? Number(e.target.value) : undefined)} /><FormControlLabel control={<Checkbox checked={step["continue-on-error"] === true} onChange={e => editStep("continue-on-error", e.target.checked)} />} label="Continue after this step fails" />
            {jsonField("Step environment variables", ["jobs", jobId, "steps", index, "env"], step.env)}
            <Stack direction="row"><Button disabled={index === 0} onClick={() => { setText(moveActionStep(text, jobId, index, index - 1)); setIndex(index - 1); }}>Move earlier</Button><Button onClick={() => { change(["jobs", jobId, "steps", index], undefined); setIndex(Math.max(0, index - 1)); }}>Remove step</Button></Stack>
          </>}<Button onClick={() => { change(["jobs", jobId, "steps", job.steps?.length || 0], { run: "echo Ready" }); setIndex(job.steps?.length || 0); }}>Add step</Button></>}
        </>}</Stack></Paper>
      <Paper sx={{ p: 2 }}><Typography variant="h6">Workflow YAML</Typography><YamlEditor value={text} onChange={setText} />
        {events.filter(event => ["schedule", "push", "workflow_run", "repository_dispatch"].includes(event)).map(event => { const enabled = triggerRows.some(row => row.workflow_key === key && row.event === event && row.enabled); return <Button key={event} onClick={() => enabled ? void toggleTrigger(event, false) : setActivation(event)}>{enabled ? "Disable" : "Activate"} {event}</Button>; })}</Paper>
    </Box>
    <CreateWorkflowDialog holder={holder.current} open={create} requestProject={props.requestProject} onClose={() => setCreate(false)} onCreated={async newKey => { setCreate(false); setKey(newKey); await refresh(); }} />
    <LaunchPanel open={launch} workflowKey={key} workflow={launchView(parsed.value, environments)} project={props.project} requestProject={props.requestProject} modelOptions={[]} blockedReason={!valid ? "Fix validation errors." : text !== saved ? "Save this workflow before running." : null} saveError={error || null} onSave={() => void save()} onClose={() => { setLaunch(false); props.onLaunchClosed(); }} onExited={() => undefined} onRunLaunched={props.onRunLaunched} previousRun={null} />
    <Dialog open={Boolean(conversion)} onClose={() => setConversion(null)} fullWidth maxWidth="md"><DialogTitle>Legacy conversion preview</DialogTitle><DialogContent><Stack spacing={1}>{conversion?.issues.map(issue => <Alert key={issue} severity="warning">{issue}</Alert>)}<Typography>Review this draft before saving. The saved source remains unchanged.</Typography><Box component="pre" sx={{ whiteSpace: "pre-wrap" }}>{conversion?.yaml}</Box></Stack></DialogContent><DialogActions><Button onClick={() => setConversion(null)}>Close</Button><Button onClick={() => { if (conversion) setText(conversion.yaml); setConversion(null); }}>Use preview as draft</Button></DialogActions></Dialog>
    <Dialog open={Boolean(activation)} onClose={() => { setActivation(null); setAuthorize(false); }}><DialogTitle>Activate {activation}</DialogTitle><DialogContent><FormControlLabel control={<Checkbox checked={authorize} onChange={e => setAuthorize(e.target.checked)} />} label="Allow this trigger to launch writing jobs automatically on this computer." /></DialogContent><DialogActions><Button onClick={() => setActivation(null)}>Cancel</Button><Button disabled={!authorize || text !== saved} onClick={() => { if (activation) void toggleTrigger(activation, true); }}>Activate trigger</Button></DialogActions></Dialog>
  </Stack>;
}
