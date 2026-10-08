import { Alert, Button, Checkbox, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Stack, Tab, Tabs, TextField, Typography } from "@mui/material";
import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import { projectPath } from "../navigation";

type Binding = { scope: string; name: string; kind: string; value: string; source: string; reference: string; revision: string };
type Environment = { name: string; approval_required: boolean; wait_minutes: number; branches: string[]; url: string };
type Template = { id: string; name: string; description?: string };

export function WorkflowSettings({ open, projectId, yaml, onClose, onEnvironments }: { open: boolean; projectId: string | null; yaml: string; onClose: () => void; onEnvironments: (names: string[]) => void }) {
  const [tab, setTab] = useState(0); const [error, setError] = useState(""); const [busy, setBusy] = useState(false);
  const [bindings, setBindings] = useState<Binding[]>([]); const [environments, setEnvironments] = useState<Environment[]>([]); const [templates, setTemplates] = useState<Template[]>([]);
  const [scope, setScope] = useState("project"); const [environment, setEnvironment] = useState(""); const [name, setName] = useState(""); const [kind, setKind] = useState("variable"); const [source, setSource] = useState("environment"); const [reference, setReference] = useState(""); const [value, setValue] = useState("");
  const [config, setConfig] = useState<Environment>({ name: "", approval_required: false, wait_minutes: 0, branches: [], url: "" });
  const [bundle, setBundle] = useState(""); const [templateName, setTemplateName] = useState(""); const [description, setDescription] = useState("");
  const endpoint = (path: string) => projectPath(path, projectId);
  async function refresh() {
    const [saved, configured, library] = await Promise.all([api<{ bindings: Binding[] }>(endpoint("/api/workflow-bindings")), api<{ environments: Environment[] }>(endpoint("/api/workflow-environments")), api<{ templates: Template[] }>("/api/workflow-library")]);
    setBindings(saved.bindings); setEnvironments(configured.environments); setTemplates(library.templates); onEnvironments(configured.environments.map(item => item.name));
  }
  useEffect(() => { if (open) { setValue(""); setError(""); void refresh().catch(e => setError(errorMessage(e))); } }, [open, projectId]);
  async function mutate(path: string, body: unknown) {
    setBusy(true); setError("");
    try { await api(endpoint(path), { method: "POST", body: JSON.stringify(body) }); setValue(""); await refresh(); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  }
  async function exportTemplate(id: string) {
    try {
      const result = await api(`/api/workflow-library?id=${encodeURIComponent(id)}`);
      const url = URL.createObjectURL(new Blob([JSON.stringify(result, null, 2)], { type: "application/json" }));
      const link = document.createElement("a"); link.href = url; link.download = `${id.replace("owner:", "")}.json`; link.click(); URL.revokeObjectURL(url);
    } catch (e) { setError(errorMessage(e)); }
  }
  const selectedScope = scope === "installation" ? "installation" : scope === "environment" ? `environment:${projectId}:${environment}` : `project:${projectId}`;
  return <Dialog open={open} onClose={() => { if (!busy) { setValue(""); onClose(); } }} fullWidth maxWidth="md"><DialogTitle>Workflow settings</DialogTitle><DialogContent><Stack spacing={2} sx={{ pt: 1 }}>
    <Tabs value={tab} onChange={(_, next: number) => setTab(next)}><Tab label="Variables and secrets" /><Tab label="Environments" /><Tab label="Workflow library" /></Tabs>
    {error && <Alert severity="error">{error}</Alert>}
    {tab === 0 && <><TextField select label="Scope" value={scope} onChange={e => setScope(e.target.value)}><MenuItem value="installation">All projects</MenuItem><MenuItem value="project">This project</MenuItem><MenuItem value="environment">Environment</MenuItem></TextField>
      {scope === "environment" && <TextField select label="Binding environment" value={environment} onChange={e => setEnvironment(e.target.value)}>{environments.map(item => <MenuItem key={item.name} value={item.name}>{item.name}</MenuItem>)}</TextField>}
      {bindings.filter(item => item.scope === selectedScope).map(item => <Stack direction="row" spacing={1} key={`${item.kind}:${item.name}`} sx={{ alignItems: "center" }}><Typography sx={{ flex: 1 }}>{item.name} · {item.kind === "secret" ? `${item.source}: ${item.source === "environment" ? item.reference : "saved credential"}` : item.value}</Typography><Button disabled={busy} onClick={() => void mutate("/api/workflow-bindings", { scope, environment, name: item.name, kind: item.kind, delete: true })}>Remove {item.name}</Button></Stack>)}
      <TextField label="Binding name" value={name} onChange={e => setName(e.target.value)} /><TextField select label="Binding type" value={kind} onChange={e => { setKind(e.target.value); setValue(""); }}><MenuItem value="variable">Variable</MenuItem><MenuItem value="secret">Secret</MenuItem></TextField>
      {kind === "secret" && <TextField select label="Secret source" value={source} onChange={e => { setSource(e.target.value); setValue(""); }}><MenuItem value="environment">Process environment variable</MenuItem><MenuItem value="credential-store">Native credential store</MenuItem></TextField>}
      {kind === "secret" && source === "environment" ? <TextField label="Environment variable reference" value={reference} onChange={e => setReference(e.target.value)} /> : <TextField label={kind === "secret" ? "New secret value" : "Variable value"} type={kind === "secret" ? "password" : "text"} autoComplete="off" value={value} onChange={e => setValue(e.target.value)} />}
      <Typography variant="body2">Project values override values for all projects. Approved environments can override project values. Saved secret values are never returned to this editor.</Typography>
      <Button disabled={busy || !name || (scope === "environment" && !environment)} onClick={() => void mutate("/api/workflow-bindings", { scope, environment, name, kind, source, reference, value })}>Save binding</Button></>}
    {tab === 1 && <>{environments.map(item => <Button key={item.name} onClick={() => setConfig(item)}>Edit {item.name}</Button>)}<TextField label="Environment name" value={config.name} onChange={e => setConfig({ ...config, name: e.target.value })} /><FormControlLabel control={<Checkbox checked={config.approval_required} onChange={e => setConfig({ ...config, approval_required: e.target.checked })} />} label="Require my approval before this job starts" /><TextField label="Wait timer (minutes)" type="number" value={config.wait_minutes} onChange={e => setConfig({ ...config, wait_minutes: Number(e.target.value) })} /><TextField label="Allowed branch patterns (one per line)" multiline value={config.branches.join("\n")} onChange={e => setConfig({ ...config, branches: e.target.value.split("\n").filter(Boolean) })} /><TextField label="Environment URL" value={config.url} onChange={e => setConfig({ ...config, url: e.target.value })} /><Button disabled={busy || !config.name} onClick={() => void mutate("/api/workflow-environments", config)}>Save environment</Button></>}
    {tab === 2 && <>{templates.map(item => <Stack direction="row" spacing={1} key={item.id}><Typography sx={{ flex: 1 }}>{item.name} {item.description}</Typography><Button onClick={() => void exportTemplate(item.id)}>Export {item.name}</Button></Stack>)}<TextField label="Library workflow name" value={templateName} onChange={e => setTemplateName(e.target.value)} /><TextField label="Library description" value={description} onChange={e => setDescription(e.target.value)} /><Button disabled={busy || !templateName} onClick={() => void mutate("/api/workflow-library", { yaml, metadata: { name: templateName, description }, sources: {}, include_project_sources: true })}>Save current workflow to library</Button><TextField label="Import workflow bundle" multiline minRows={4} value={bundle} onChange={e => setBundle(e.target.value)} /><Button disabled={busy || !bundle} onClick={() => { try { void mutate("/api/workflow-library", JSON.parse(bundle)); } catch (e) { setError(errorMessage(e)); } }}>Import bundle</Button></>}
  </Stack></DialogContent><DialogActions><Button onClick={() => { setValue(""); onClose(); }} disabled={busy}>Close</Button></DialogActions></Dialog>;
}
