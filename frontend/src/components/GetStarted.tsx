import {
  Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle,
  FormControl, InputLabel, Link, MenuItem, Paper, Select, Stack, TextField, Typography,
} from "@mui/material";
import { useEffect, useRef, useState } from "react";

import { api, errorMessage } from "../api";
import { editorHolder } from "../editor-session";
import { projectPath } from "../navigation";
import type { AgentReadiness, AgentsResponse, JsonScalar, ProjectRecord, WorkflowTemplate } from "../types";
import { CreateWorkflowDialog } from "./CreateWorkflowDialog";

interface GetStartedProps {
  project: ProjectRecord;
  requestProject: string | null;
  runSucceeded: boolean;
  onWorkflowCreated: (key: string) => Promise<void>;
  onRunLaunched: (id: string) => void;
  onOpenProject: () => void;
  onClose: () => void;
}

function readinessLabel(row: AgentReadiness | undefined, installed: boolean, checking: boolean): string {
  if (!installed) return "Not installed";
  if (!row) return checking ? "Checking…" : "Check failed";
  if (row.ready) return "Ready to connect";
  return row.error_code === "agent_auth_error" ? "Sign in required" : "Check failed";
}

export function GetStarted({ project, requestProject, runSucceeded, onWorkflowCreated, onRunLaunched, onOpenProject, onClose }: GetStartedProps) {
  const [inventory, setInventory] = useState<AgentsResponse | null>(null);
  const [readiness, setReadiness] = useState<AgentReadiness[]>([]);
  const [checking, setChecking] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [check, setCheck] = useState(0);
  const [complete, setComplete] = useState<boolean | null>(null);
  const [newWorkflow, setNewWorkflow] = useState(false);
  const [workflow, setWorkflow] = useState<string | null>(null);
  const [template, setTemplate] = useState<WorkflowTemplate | null>(null);
  const [inputs, setInputs] = useState<Record<string, JsonScalar>>({});
  const [model, setModel] = useState("");
  const [launching, setLaunching] = useState(false);
  const holder = useRef(editorHolder());
  const models = Array.from(new Set(readiness.filter((row) => row.ready).flatMap((row) => row.models)));

  useEffect(() => {
    let active = true;
    void api<{ runs: Array<{ id: string }> }>(`/api/runs?project=${encodeURIComponent(project.id)}&status=succeeded&limit=1`)
      .then((value) => { if (active) setComplete(runSucceeded || value.runs.length > 0); })
      .catch((caught: unknown) => { if (active) { setError(errorMessage(caught)); setComplete(false); } });
    return () => { active = false; };
  }, [project.id, runSucceeded]);
  useEffect(() => { if (runSucceeded) setComplete(true); }, [runSucceeded]);

  useEffect(() => {
    let active = true;
    setChecking(true);
    setReadiness([]);
    setError(null);
    void api<AgentsResponse>("/api/agents")
      .then(async (inventory) => {
        if (!active) return;
        setInventory(inventory);
        const value = await api<{ agents: AgentReadiness[] }>(projectPath("/api/agents/check", requestProject), { method: "POST", body: "{}" });
        if (!active) return;
        setReadiness(value.agents);
        setModel((current) => value.agents.some((row) => row.ready && row.models.includes(current))
          ? current : value.agents.find((row) => row.ready)?.models[0] ?? "");
      })
      .catch((caught: unknown) => { if (active) setError(errorMessage(caught)); })
      .finally(() => { if (active) setChecking(false); });
    return () => { active = false; };
  }, [check, requestProject]);

  async function launch() {
    if (!workflow) return;
    setLaunching(true);
    setError(null);
    try {
      const response = await api<{ run_id: string }>(projectPath("/api/runs", requestProject), {
        method: "POST", body: JSON.stringify({ workflow_key: workflow, project_id: project.id, model, inputs }),
      });
      onRunLaunched(response.run_id);
    } catch (caught) { setError(errorMessage(caught)); }
    finally { setLaunching(false); }
  }

  return <Dialog open onClose={onClose} fullWidth maxWidth="lg" aria-labelledby="get-started-title">
    <Box component="section" aria-labelledby="get-started-title" sx={{ display: "flex", flexDirection: "column", minHeight: 0 }}>
      <DialogTitle id="get-started-title">Get started</DialogTitle>
      <DialogContent dividers>
        <Stack spacing={2}>
          <Typography>Relay runs coding jobs in order, shows their progress, and asks for your approval when a workflow needs it.</Typography>
          {complete && <Alert severity="success">Your first run completed. You can use this checklist again for another workflow.</Alert>}
          <Box>
            <Typography variant="h6">1. Project ✓</Typography>
            <Typography>{project.display_name}</Typography>
            <Typography variant="body2" color="text.secondary">{project.canonical_path}</Typography>
            <Button onClick={onOpenProject}>Choose another project</Button>
          </Box>
          <Box>
            <Typography variant="h6">2. Agents</Typography>
            <Typography variant="body2">One working agent is enough. A connection check reads available models; authentication is verified when a run starts.</Typography>
            <Box sx={{ display: "grid", gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr", lg: "repeat(5, 1fr)" }, gap: 1, mt: 1 }}>
              {inventory?.agents.map((agent) => {
                const row = readiness.find((item) => item.id === agent.id);
                const label = readinessLabel(row, agent.installed, checking);
                return <Paper component="article" aria-label={agent.display_name} key={agent.id} variant="outlined" sx={{ p: 2 }}>
                  <Stack spacing={1}>
                    <Typography variant="subtitle1">{agent.display_name}</Typography>
                    <Typography>{row?.ready ? "✓ " : "○ "}{label}</Typography>
                    {!agent.installed && <Link href={agent.install_url} target="_blank" rel="noopener noreferrer">Install {agent.display_name}</Link>}
                    {agent.installed && row && !row.ready && <>
                      <Typography variant="body2">{row.reason ?? "The agent returned no models. Check its installation and sign-in."}</Typography>
                      <Typography variant="body2">{row.login_guidance}</Typography>
                      <Box component="code">{row.login_command}</Box>
                      <Button onClick={() => void navigator.clipboard.writeText(row.login_command).catch((caught: unknown) => setError(errorMessage(caught)))}>Copy sign-in command</Button>
                    </>}
                    {row?.cleanup_warning && <Alert severity="warning">{row.cleanup_warning}</Alert>}
                  </Stack>
                </Paper>;
              })}
            </Box>
            <Button onClick={() => setCheck((value) => value + 1)} disabled={checking}>{checking ? "Checking agents…" : "Check again"}</Button>
            {!checking && readiness.length > 0 && !readiness.some((row) => row.ready) && <Alert severity="warning">Install and sign in to one agent, then choose Check again.</Alert>}
          </Box>
          <Box>
            <Typography variant="h6">3. First workflow {workflow ? "✓" : ""}</Typography>
            <Button variant="outlined" onClick={() => setNewWorkflow(true)}>Start from a template</Button>
            <Button onClick={() => setNewWorkflow(true)}>Blank workflow</Button>
            {workflow && <Typography variant="body2">{template?.name ?? "Blank workflow"} is saved in your project.</Typography>}
          </Box>
          <Box>
            <Typography variant="h6">4. First run {complete ? "✓" : ""}</Typography>
            {!template ? <Typography variant="body2">Choose a template above, or close this checklist to add jobs in the workflow editor.</Typography> : <Stack spacing={2} sx={{ mt: 1 }}>
              {Object.entries(template.inputs).map(([key, definition]) => definition.type === "enum" ? <FormControl key={key}>
                <InputLabel id={`setup-input-${key}`}>{definition.description ?? key}</InputLabel>
                <Select labelId={`setup-input-${key}`} label={definition.description ?? key} value={inputs[key] ?? ""}
                  onChange={(event) => setInputs((current) => ({ ...current, [key]: event.target.value }))}>
                  {definition.constraints?.values?.map((value) => <MenuItem key={value} value={value}>{value}</MenuItem>)}
                </Select>
              </FormControl> : <TextField key={key} label={definition.description ?? key} value={inputs[key] ?? ""}
                onChange={(event) => setInputs((current) => ({ ...current, [key]: event.target.value }))} />)}
              <FormControl><InputLabel id="setup-model">Model</InputLabel><Select labelId="setup-model" label="Model" value={model} onChange={(event) => setModel(event.target.value)}>
                {models.map((value) => <MenuItem key={value} value={value}>{value}</MenuItem>)}
              </Select></FormControl>
              <Button variant="contained" onClick={() => void launch()} disabled={launching || checking || !model || !models.includes(model)}>Run workflow</Button>
            </Stack>}
          </Box>
          {error && <Alert severity="error">{error}</Alert>}
        </Stack>
      </DialogContent>
      <DialogActions><Button onClick={onClose}>Close checklist</Button></DialogActions>
      <CreateWorkflowDialog open={newWorkflow} requestProject={requestProject} holder={holder.current} onClose={() => setNewWorkflow(false)}
        onCreated={async (key, selected) => {
          await onWorkflowCreated(key);
          setWorkflow(key); setTemplate(selected);
          setInputs(Object.fromEntries(Object.entries(selected?.inputs ?? {}).flatMap(([name, definition]) => definition.default === undefined ? [] : [[name, definition.default]])));
        }} />
    </Box>
  </Dialog>;
}
