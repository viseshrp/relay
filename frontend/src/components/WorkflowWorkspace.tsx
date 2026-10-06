import {
  Alert,
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  FormControl,
  FormControlLabel,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { api, errorMessage, RelayApiError } from "../api";
import { projectPath, stageLabel } from "../navigation";
import type { AgentOptions, AgentsResponse, HandoffWarning, JsonScalar, ProjectRecord, WorkflowDocumentResponse, WorkflowDraft } from "../types";
import {
  canonicalYaml,
  flowElements,
  mutateWorkflow,
  nextNodeId,
  nodeDefaults,
  parseWorkflow,
  type WorkflowNodeValue,
} from "../workflow";
import { FlowCanvas } from "./FlowCanvas";
import { AgentConfiguration } from "./AgentConfiguration";
import { PromptEditor } from "./PromptEditor";
import { ModelPicker } from "./ModelPicker";

const YamlEditor = lazy(() =>
  import("./YamlEditor").then((module) => ({ default: module.YamlEditor })),
);

const LEASE_RENEW_MS = 30_000;
const AUTOSAVE_DELAY_MS = 600;

interface WorkflowWorkspaceProps {
  onRunLaunched: (runId: string) => void;
  project: ProjectRecord;
  requestProject: string | null;
  initialWorkflow: string | null;
  onWorkflowLoaded: (key: string) => void;
  onNavigationReady: (callback: (() => Promise<void>) | null) => void;
}

function workflowPath(key: string, suffix = ""): string {
  // "nested/my flow" + "/save" -> "/api/workflows/nested/my%20flow/save".
  const encoded = key
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/");
  return `/api/workflows/${encoded}${suffix}`;
}

type LaunchInputValue = JsonScalar | undefined;

function scalarDefault(value: unknown): LaunchInputValue {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return value;
  }
  return undefined;
}

function createHolder(): string {
  const existing = sessionStorage.getItem("relay.editor-holder");
  if (existing) return existing;
  const holder = crypto.randomUUID();
  sessionStorage.setItem("relay.editor-holder", holder);
  return holder;
}

export function WorkflowWorkspace({ onRunLaunched, project, requestProject, initialWorkflow, onWorkflowLoaded, onNavigationReady }: WorkflowWorkspaceProps) {
  const holder = useRef(createHolder());
  const initialKey = useRef(initialWorkflow);
  const [inventory, setInventory] = useState<Array<{ key: string; name: string }>>([]);
  const [newWorkflow, setNewWorkflow] = useState(false);
  const [newKey, setNewKey] = useState("");
  const [advanced, setAdvanced] = useState(false);
  const [addingStage, setAddingStage] = useState(false);
  const [stageName, setStageName] = useState("Check project");
  const [stageKind, setStageKind] = useState("command");
  const [warnings, setWarnings] = useState<HandoffWarning[]>([]);
  const [handoffHelp, setHandoffHelp] = useState(false);
  const [promptDirty, setPromptDirty] = useState(false);
  const [workflowKey, setWorkflowKey] = useState("workflow");
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [yamlText, setYamlText] = useState("");
  const [savedYaml, setSavedYaml] = useState("");
  const [baseHash, setBaseHash] = useState("");
  const [draft, setDraft] = useState<WorkflowDraft | null>(null);
  const [leaseReady, setLeaseReady] = useState(false);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [formattingYaml, setFormattingYaml] = useState<string | null>(null);
  const [agents, setAgents] = useState<AgentsResponse | null>(null);
  const [launchInputs, setLaunchInputs] = useState<Record<string, LaunchInputValue>>({});
  const [launchModel, setLaunchModel] = useState("");
  const [cleanupPolicy, setCleanupPolicy] = useState("clean_on_success");
  const [entryPoint, setEntryPoint] = useState("");
  const [launching, setLaunching] = useState(false);

  const parsed = useMemo(() => parseWorkflow(yamlText), [yamlText]);
  const graph = useMemo(() => flowElements(parsed.value), [parsed.value]);
  const definition = selectedNode ? parsed.value?.nodes[selectedNode] : undefined;
  const dirty = loadedKey !== null && yamlText !== savedYaml;
  const draftWrites = useRef<Promise<void>>(Promise.resolve());
  const flushDraft = useCallback(async () => {
    if (promptDirty) throw new Error("Save the agent's instructions before leaving this stage.");
    if (!dirty || loadedKey === null) return;
    if (!leaseReady) throw new Error("Save or recover this workflow before switching projects. Its editing lease is unavailable.");
    const write = draftWrites.current.catch(() => undefined).then(async () => {
      const response = await api<{ draft: WorkflowDraft }>(projectPath(workflowPath(loadedKey, "/draft"), requestProject), {
        method: "POST", body: JSON.stringify({ yaml: yamlText, base_hash: baseHash, holder: holder.current }),
      });
      setDraft(response.draft);
    });
    draftWrites.current = write;
    await write;
  }, [dirty, loadedKey, leaseReady, requestProject, yamlText, baseHash, promptDirty]);
  useEffect(() => { onNavigationReady(flushDraft); return () => onNavigationReady(null); }, [onNavigationReady, flushDraft]);
  const flushCurrent = useRef(flushDraft);
  useEffect(() => { flushCurrent.current = flushDraft; }, [flushDraft]);
  useEffect(() => {
    if (!dirty && !promptDirty) return;
    const guard = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [dirty, promptDirty]);

  const acquireLease = useCallback(async (key: string) => {
    await api<{ lease: { expires_at: string } }>(projectPath(workflowPath(key, "/lease"), requestProject), {
      method: "POST",
      body: JSON.stringify({ holder: holder.current }),
    });
    setLeaseReady(true);
  }, [requestProject]);

  const applyDocument = useCallback((document: WorkflowDocumentResponse) => {
    const recovered = document.draft?.yaml ?? document.yaml;
    setYamlText(recovered);
    setSavedYaml(document.yaml);
    setBaseHash(document.base_hash);
    setDraft(document.draft);
    setWarnings(document.warnings);
    setSelectedNode(null);
  }, []);

  const loadWorkflow = useCallback(
    async (key: string) => {
      const normalized = key.trim();
      if (!normalized) return;
      try { await flushCurrent.current(); } catch (caught) { setError(errorMessage(caught)); return; }
      setBusy(true);
      setError(null);
      setNotice(null);
      setLeaseReady(false);
      try {
        await acquireLease(normalized);
        const document = await api<WorkflowDocumentResponse>(projectPath(workflowPath(normalized), requestProject));
        if (document.project.id !== project.id) throw new Error("This workflow belongs to another project. Choose the project again before editing.");
        applyDocument(document);
        setLoadedKey(normalized);
        setWorkflowKey(normalized);
        onWorkflowLoaded(normalized);
      } catch (caught) {
        setError(errorMessage(caught));
      } finally {
        setBusy(false);
      }
    },
    [acquireLease, applyDocument, project.id, requestProject, onWorkflowLoaded],
  );

  useEffect(() => {
    void api<AgentsResponse>("/api/agents").then(setAgents).catch(() => setAgents(null));
    let active = true;
    void api<{ workflows: Array<{ key: string; name: string }> }>(projectPath("/api/workflows", requestProject)).then((response) => {
      if (!active) return;
      setInventory(response.workflows);
      const key = initialKey.current ?? response.workflows.find((item) => item.key === "workflow.yaml")?.key ?? response.workflows[0]?.key;
      if (key) void loadWorkflow(key);
    }).catch((caught: unknown) => { if (active) setError(errorMessage(caught)); });
    return () => { active = false; };
  }, [loadWorkflow, requestProject]);

  useEffect(() => {
    if (loadedKey === null) return;
    const interval = window.setInterval(() => {
      void acquireLease(loadedKey).catch((caught: unknown) => {
        setLeaseReady(false);
        setError(errorMessage(caught));
      });
    }, LEASE_RENEW_MS);
    return () => window.clearInterval(interval);
  }, [acquireLease, loadedKey]);

  useEffect(() => {
    if (!dirty || loadedKey === null || !leaseReady || busy) return;
    const timer = window.setTimeout(() => {
      void flushDraft().catch((caught: unknown) => setError(errorMessage(caught)));
    }, AUTOSAVE_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [dirty, leaseReady, loadedKey, busy, flushDraft]);

  useEffect(() => {
    const definitions = parsed.value?.inputs ?? {};
    setLaunchInputs((current) =>
      Object.fromEntries(
        Object.entries(current).filter(([name]) => Object.hasOwn(definitions, name)),
      ),
    );
  }, [parsed.value?.inputs]);

  function mutate(mutation: Parameters<typeof mutateWorkflow>[1]) {
    try {
      setYamlText((current) => mutateWorkflow(current, mutation));
      setError(null);
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  function addNode() {
    if (promptDirty) { setError("Save the agent's instructions before adding a stage."); return; }
    // "Check project" becomes "check_project"; punctuation is removed from the internal stage key.
    const prefix = stageName.trim().toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "step";
    const id = nextNodeId(parsed.value, /^[a-z]/.test(prefix) ? prefix : `step_${prefix}`);
    const previous = Object.keys(parsed.value?.nodes ?? {}).at(-1);
    mutate((document) => document.setIn(["nodes", id], { ...nodeDefaults(stageKind), ...(previous ? { needs: [previous] } : {}) }));
    setSelectedNode(id);
    setAddingStage(false);
  }

  function deleteNode() {
    if (promptDirty) { setError("Save the agent's instructions before removing a stage."); return; }
    if (selectedNode === null) return;
    mutate((document, value) => {
      document.deleteIn(["nodes", selectedNode]);
      for (const [id, node] of Object.entries(value.nodes)) {
        if (id !== selectedNode && node.needs?.includes(selectedNode)) {
          document.setIn(
            ["nodes", id, "needs"],
            node.needs.filter((need) => need !== selectedNode),
          );
        }
      }
    });
    setSelectedNode(null);
  }

  function setNodeField(field: string, value: unknown) {
    if (selectedNode === null) return;
    mutate((document) => {
      if (value === "" || value === undefined) document.deleteIn(["nodes", selectedNode, field]);
      else document.setIn(["nodes", selectedNode, field], value);
    });
  }

  function setNodeType(type: string) {
    if (promptDirty) { setError("Save the agent's instructions before changing this stage's action."); return; }
    if (selectedNode === null) return;
    const needs = definition?.needs;
    mutate((document) =>
      document.setIn(["nodes", selectedNode], {
        ...nodeDefaults(type),
        ...(needs && needs.length > 0 ? { needs } : {}),
      }),
    );
  }

  function setAgentOption(agentId: string, field: keyof AgentOptions, value: string) {
    if (selectedNode === null) return;
    mutate((document, workflow) => {
      const current = { ...workflow.nodes[selectedNode].agent_options };
      const options = { ...current[agentId] };
      if (value === "") delete options[field];
      else options[field] = value;
      if (Object.keys(options).length === 0) delete current[agentId];
      else current[agentId] = options;
      if (Object.keys(current).length === 0) document.deleteIn(["nodes", selectedNode, "agent_options"]);
      else document.setIn(["nodes", selectedNode, "agent_options"], current);
    });
  }

  function setAgentModel(model: string) {
    if (selectedNode === null) return;
    mutate((document, workflow) => {
      if (model === "") document.deleteIn(["nodes", selectedNode, "model"]);
      else document.setIn(["nodes", selectedNode, "model"], model);
      const current = { ...workflow.nodes[selectedNode].agent_options };
      for (const [agentId, options] of Object.entries(current)) {
        const remaining = { ...options };
        delete remaining.effort;
        if (Object.keys(remaining).length === 0) delete current[agentId];
        else current[agentId] = remaining;
      }
      if (Object.keys(current).length === 0) document.deleteIn(["nodes", selectedNode, "agent_options"]);
      else document.setIn(["nodes", selectedNode, "agent_options"], current);
    });
  }

  async function persistSave(canonical: string) {
    if (loadedKey === null) return;
    setBusy(true);
    setError(null);
    try {
      await draftWrites.current;
      await api<{ ok: boolean }>(projectPath(workflowPath(loadedKey, "/save"), requestProject), {
        method: "POST",
        body: JSON.stringify({
          yaml: canonical,
          base_hash: baseHash,
          holder: holder.current,
        }),
      });
      const refreshed = await api<WorkflowDocumentResponse>(projectPath(workflowPath(loadedKey), requestProject));
      applyDocument(refreshed);
      setNotice("Workflow saved and validated.");
    } catch (caught) {
      if (caught instanceof RelayApiError && caught.status === 409) {
        setError(`${errorMessage(caught)} Your recovery draft remains available.`);
      } else {
        setError(errorMessage(caught));
      }
    } finally {
      setFormattingYaml(null);
      setBusy(false);
    }
  }

  function requestSave() {
    if (promptDirty) { setError("Save the agent's instructions before saving the workflow."); return; }
    try {
      const canonical = canonicalYaml(yamlText);
      if (canonical !== yamlText) setFormattingYaml(canonical);
      else void persistSave(canonical);
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }

  async function launch() {
    if (loadedKey === null) return;
    setLaunching(true);
    setError(null);
    try {
      const suppliedInputs = Object.fromEntries(
        Object.entries(launchInputs).flatMap(([name, value]) =>
          value === undefined ? [] : [[name, value]],
        ),
      );
      const response = await api<{ run_id: string }>(projectPath("/api/runs", requestProject), {
        method: "POST",
        body: JSON.stringify({
          workflow_key: loadedKey,
          project_id: project.id,
          inputs: suppliedInputs,
          ...(launchModel ? { model: launchModel } : {}),
          cleanup_policy: cleanupPolicy,
          ...(entryPoint ? { entry_point: entryPoint } : {}),
        }),
      });
      onRunLaunched(response.run_id);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setLaunching(false);
    }
  }

  const modelOptions = Array.from(
    new Set(agents?.agents.flatMap((agent) => agent.models.map((model) => model.value)) ?? []),
  ).sort();
  const inputDefinitions = parsed.value?.inputs ?? {};
  const candidateIds = Array.from(new Set([
    ...(definition?.agents ?? []),
    ...(parsed.value?.agents ?? []),
    ...(agents?.preferences ?? []),
  ]));
  const effectiveModel = (typeof definition?.model === "string" ? definition.model : "")
    || launchModel || parsed.value?.model || "";

  async function createWorkflow() {
    setBusy(true);
    setError(null);
    try {
      // "Release review" becomes "release-review"; the display name keeps the owner's wording.
      const slug = newKey.trim().toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-+|-+$/g, "") || "workflow";
      const key = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])$/i.test(slug) ? `workflow-${slug}` : slug;
      const created = await api<{ key: string }>(projectPath("/api/workflows", requestProject), {
        method: "POST", body: JSON.stringify({ key, name: newKey.trim(), holder: holder.current }),
      });
      const refreshed = await api<{ workflows: Array<{ key: string; name: string }> }>(projectPath("/api/workflows", requestProject));
      setInventory(refreshed.workflows);
      await loadWorkflow(created.key);
      setNewWorkflow(false);
      setNewKey("");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally { setBusy(false); }
  }

  return (
    <Stack spacing={2}>
      <Box>
        <Typography variant="h4">{parsed.value?.name || "Choose a workflow"}</Typography>
        <Typography color="text.secondary">1. Choose or create a workflow. 2. Set up its stages. 3. Save and start work.</Typography>
      </Box>
      <Paper className="toolbar-card" variant="outlined">
        <Stack
          direction={{ xs: "column", md: "row" }}
          spacing={1.5}
          sx={{ alignItems: { md: "center" } }}
        >
          <FormControl size="small" sx={{ minWidth: 230 }}>
            <InputLabel id="workflow-picker">Workflow</InputLabel>
            <Select labelId="workflow-picker" label="Workflow" value={inventory.some((item) => item.key === loadedKey) ? loadedKey ?? "" : ""} onChange={(event) => void loadWorkflow(event.target.value)} disabled={busy}>
              {inventory.map((item) => <MenuItem key={item.key} value={item.key}>{item.name}</MenuItem>)}
            </Select>
          </FormControl>
          <Button variant="outlined" onClick={() => setNewWorkflow(true)}>New workflow</Button>
          <Button variant="contained" onClick={requestSave} disabled={!dirty || busy || !leaseReady}>
            Save
          </Button>
          <Button onClick={() => setAddingStage(true)} disabled={parsed.value === null || !leaseReady}>Add stage</Button>
          <Box sx={{ flex: 1 }} />
          <Chip
            size="small"
            color={leaseReady ? "success" : "warning"}
            label={leaseReady ? "Ready to edit" : "Editing unavailable"}
          />
          {draft && <Chip size="small" label={`Draft ${draft.validation_state}`} />}
          {dirty && <Chip size="small" color="primary" variant="outlined" label="Unsaved" />}
        </Stack>
      </Paper>

      {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}
      {notice && <Alert severity="success" onClose={() => setNotice(null)}>{notice}</Alert>}
      {warnings.map((warning) => <Alert key={`${warning.workflow_key ?? ""}-${warning.scope_path}-${warning.output}`} severity="warning" action={<Button onClick={() => setHandoffHelp(true)}>Retain the report</Button>}>
        {warning.workflow_key ? `${warning.workflow_key} · ` : ""}{stageLabel(warning.scope_path)}: {warning.artifact} is only checked for existence. {warning.message}
      </Alert>)}
      {loadedKey && Object.keys(parsed.value?.nodes ?? {}).length === 0 && <Alert severity="info" action={<Button onClick={() => setAddingStage(true)}>Add first stage</Button>}>Your workflow is empty. Add a command, agent task, or review step to begin.</Alert>}
      {parsed.errors.length > 0 && (
        <Alert severity="warning">{parsed.errors.join(" ")}</Alert>
      )}

      <Box>
        <Paper className="canvas-panel" variant="outlined">
          <Typography variant="subtitle2" sx={{ p: 2 }}>Workflow stages · click a stage to configure it</Typography>
          <FlowCanvas
            nodes={graph.nodes}
            edges={graph.edges}
            selectedId={selectedNode}
            onSelect={(id) => { if (promptDirty) setError("Save the agent's instructions before selecting another stage."); else setSelectedNode(id); }}
          />
        </Paper>
        <Accordion expanded={advanced} onChange={(_event, open) => setAdvanced(open)}>
          <AccordionSummary><Typography>Advanced workflow settings and YAML</Typography></AccordionSummary>
          <AccordionDetails>
          <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
            <TextField size="small" label="Workflow key" value={workflowKey} onChange={(event) => setWorkflowKey(event.target.value)} />
            <Button onClick={() => void loadWorkflow(workflowKey)}>Load</Button>
          </Stack>
          <Box className="yaml-panel">
          <Suspense fallback={<Box className="loading-panel">Loading YAML editor…</Box>}>
            <YamlEditor value={yamlText} onChange={setYamlText} />
          </Suspense>
          </Box>
          </AccordionDetails>
        </Accordion>
      </Box>

      {selectedNode && definition && (
        <Paper className="section-card" variant="outlined">
          <Stack spacing={2}>
            <Stack direction="row" spacing={2} sx={{ alignItems: "center" }}>
              <Typography variant="h6" sx={{ flex: 1 }}>{stageLabel(selectedNode)}</Typography>
              <Button color="error" onClick={deleteNode}>Remove stage</Button>
            </Stack>
            <Box className="field-grid">
              <FormControl size="small">
                <InputLabel id="stage-action">What this stage does</InputLabel>
                <Select
                  labelId="stage-action"
                  label="What this stage does"
                  value={definition.type}
                  onChange={(event) => setNodeType(event.target.value)}
                >
                  {['agent', 'command', 'human_wait', 'condition', 'loop', 'subworkflow'].map((type) => (
                    <MenuItem key={type} value={type}>{{ agent: "Agent work", command: "Run a command", human_wait: "Human review", condition: "Check a result", loop: "Repeat stages", subworkflow: "Run another workflow" }[type]}</MenuItem>
                  ))}
                </Select>
              </FormControl>
              <FormControl size="small">
                <InputLabel id="stage-dependencies">Start after</InputLabel>
                <Select multiple labelId="stage-dependencies" label="Start after" value={definition.needs ?? []} onChange={(event) => setNodeField("needs", event.target.value)} renderValue={(items) => items.map(stageLabel).join(", ")}>
                  {Object.keys(parsed.value?.nodes ?? {}).filter((id) => id !== selectedNode).map((id) => <MenuItem key={id} value={id}>{stageLabel(id)}</MenuItem>)}
                </Select>
              </FormControl>
              {(definition.type === "agent" || definition.type === "command") && (
                <FormControlLabel
                  control={
                    <Switch
                      checked={definition.writes === true}
                      onChange={(event) => setNodeField("writes", event.target.checked)}
                    />
                  }
                  label="Allow file changes"
                />
              )}
              {definition.type === "agent" && (
                <>
                  <FormControlLabel
                    control={<Switch checked={definition.auto_retry !== false}
                      onChange={(event) => setNodeField("auto_retry", event.target.checked)} />}
                    label="Allow automatic retries for this step"
                  />
                  <ModelPicker key={`${selectedNode}-${candidateIds.join(",")}`} agents={agents?.agents.filter((agent) => candidateIds.includes(agent.id)) ?? []} value={typeof definition.model === "string" ? definition.model : ""} project={requestProject} onChange={setAgentModel} />
                  <TextField
                    size="small"
                    label="Exact model override"
                    helperText="Choose a model offered by the selected tool. Leave empty to use the workflow's model."
                    value={typeof definition.model === "string" ? definition.model : ""}
                    onChange={(event) => setAgentModel(event.target.value)}
                    slotProps={{ htmlInput: { list: "relay-model-options" } }}
                  />
                  <FormControl size="small">
                    <InputLabel id="agent-tools-label" shrink>Agent tools</InputLabel>
                    <Select
                      multiple
                      labelId="agent-tools-label"
                      label="Agent tools"
                      displayEmpty
                      notched
                      renderValue={(selected) => selected.length === 0 ? "Workflow and owner preferences"
                        : selected.map((id) => agents?.agents.find((agent) => agent.id === id)?.display_name ?? id).join(", ")}
                      value={definition.agents ?? []}
                      onChange={(event) => setNodeField("agents", event.target.value)}
                    >
                      {agents?.agents.map((agent) => <MenuItem key={agent.id} value={agent.id}>{agent.display_name}</MenuItem>)}
                    </Select>
                  </FormControl>
                </>
              )}
              {definition.type === "command" && (
                <Stack spacing={1}>
                  <TextField size="small" label="Program" value={Array.isArray(definition.run) ? String(definition.run[0] ?? "") : ""} onChange={(event) => setNodeField("run", [event.target.value, ...(Array.isArray(definition.run) ? definition.run.slice(1) : [])])} />
                  <TextField size="small" label="Arguments (one per line)" multiline minRows={2} value={Array.isArray(definition.run) ? definition.run.slice(1).join("\n") : ""} onChange={(event) => {
                    // "a b\n--fast" becomes ["a b", "--fast"]; no shell quoting or expansion occurs.
                    setNodeField("run", [Array.isArray(definition.run) ? definition.run[0] : "", ...(event.target.value === "" ? [] : event.target.value.split("\n"))]);
                  }} helperText="Each line is passed as one argument. For Git status, use status and --short on separate lines." />
                <Accordion><AccordionSummary>Advanced command arguments</AccordionSummary><AccordionDetails>
                <TextField
                  key={`${selectedNode}-${JSON.stringify(definition.run)}`}
                  size="small"
                  label="Argument vector as JSON"
                  defaultValue={JSON.stringify(definition.run ?? [])}
                  onBlur={(event) => {
                    try {
                      const value: unknown = JSON.parse(event.target.value);
                      if (!Array.isArray(value) || !value.every((item) => typeof item === "string")) {
                        throw new Error("Command arguments must be a JSON string array.");
                      }
                      setNodeField("run", value);
                    } catch (caught) {
                      setError(errorMessage(caught));
                    }
                  }}
                />
                </AccordionDetails></Accordion>
                </Stack>
              )}
              {definition.type === "human_wait" && (
                <TextField
                  size="small"
                  label="Review instructions and expected response"
                  multiline minRows={4}
                  value={typeof definition.prompt === "string" ? definition.prompt : ""}
                  onChange={(event) => setNodeField("prompt", event.target.value)}
                />
              )}
              {definition.type === "condition" && (
                <TextField
                  size="small"
                  label="Expression"
                  value={typeof definition.expr === "string" ? definition.expr : ""}
                  onChange={(event) => setNodeField("expr", event.target.value)}
                />
              )}
              {definition.type === "loop" && (
                <TextField
                  size="small"
                  type="number"
                  label="Maximum iterations"
                  value={typeof definition.max_iterations === "number" ? definition.max_iterations : 1}
                  onChange={(event) => setNodeField("max_iterations", Number(event.target.value))}
                />
              )}
              {definition.type === "subworkflow" && (
                <TextField
                  size="small"
                  label="Workflow key"
                  value={typeof definition.workflow === "string" ? definition.workflow : ""}
                  onChange={(event) => setNodeField("workflow", event.target.value)}
                />
              )}
            </Box>
            {definition.type === "agent" && loadedKey && selectedNode && (
              <PromptEditor
                key={`${loadedKey}-${selectedNode}`}
                workflowPath={workflowPath(loadedKey)}
                reference={(Array.isArray(definition.prompts) ? definition.prompts : []).find((prompt) => typeof prompt.local === "string")?.local ?? null}
                newReference={`prompts/ui/${loadedKey.replace(/\.(yaml|yml)$/, "")}/${selectedNode}.md`}
                project={requestProject} holder={holder.current} disabled={!leaseReady}
                onDirty={setPromptDirty}
                onSaved={(reference) => {
                  const prompts = Array.isArray(definition.prompts) ? definition.prompts : [];
                  if (!prompts.some((prompt) => prompt.local === reference)) setNodeField("prompts", [...prompts, { local: reference }]);
                }}
              />
            )}
            {definition.type === "agent" && candidateIds.map((agentId) => {
              const agent = agents?.agents.find((item) => item.id === agentId);
              return agent ? (
                <AgentConfiguration
                  key={`${selectedNode}-${agentId}`}
                  agent={agent}
                  model={effectiveModel}
                  project={requestProject}
                  options={definition.agent_options?.[agentId] ?? {}}
                  onChange={(field, value) => setAgentOption(agentId, field, value)}
                />
              ) : null;
            })}
            {definition.type === "agent" && candidateIds.length === 0 && (
              <Typography variant="body2" color="text.secondary">Select an agent tool to configure its effort and permission mode.</Typography>
            )}
          </Stack>
        </Paper>
      )}

      <Paper className="section-card" variant="outlined">
        <Stack spacing={2}>
          <Box>
            <Typography variant="h6">Start work</Typography>
            <Typography variant="body2" color="text.secondary">
              Your tools work on a separate Git branch. Work continues automatically unless a workflow stage or tool asks for your input.
            </Typography>
          </Box>
          <FormControlLabel
            control={<Switch checked={parsed.value?.recovery?.enabled === true}
              disabled={!leaseReady || parsed.value === null}
              onChange={(event) => setYamlText(mutateWorkflow(yamlText, (document) => {
                document.setIn(["recovery", "enabled"], event.target.checked);
              }))} />}
            label="Automatic recovery"
          />
          <Typography variant="body2" color="text.secondary">
            Retry eligible agent failures up to twice. Relay keeps the same model,
            settings, and original instructions, then adds the error and a repair
            instruction. Unsafe failures and exhausted retries stop visibly.
          </Typography>
          <Box className="field-grid">
            {Object.entries(inputDefinitions).map(([name, input]) => {
              const supplied = launchInputs[name];
              const value = supplied === undefined
                ? scalarDefault(input.default)
                : supplied;
              if (input.type === "boolean") {
                return (
                  <FormControlLabel
                    key={name}
                    control={
                      <Checkbox
                        checked={value === true}
                        indeterminate={value === undefined}
                        onChange={(event) =>
                          setLaunchInputs((current) => ({ ...current, [name]: event.target.checked }))
                        }
                      />
                    }
                    label={`${name}${input.required ? " *" : ""}`}
                  />
                );
              }
              if (input.type === "enum") {
                const values = Array.isArray(input.constraints?.values)
                  ? input.constraints.values.filter(
                      (item): item is JsonScalar =>
                        item === null || ["string", "number", "boolean"].includes(typeof item),
                    )
                  : [];
                return (
                  <FormControl key={name} size="small" required={input.required}>
                    <InputLabel id={`input-${name}`}>{name}</InputLabel>
                    <Select
                      labelId={`input-${name}`}
                      label={name}
                      value={value === undefined ? "" : JSON.stringify(value)}
                      onChange={(event) =>
                        setLaunchInputs((current) => ({
                          ...current,
                          [name]: event.target.value === ""
                            ? undefined
                            : JSON.parse(event.target.value) as JsonScalar,
                        }))
                      }
                    >
                      <MenuItem value="" disabled={input.required === true}>
                        {input.required ? "Select a value" : "Unset"}
                      </MenuItem>
                      {values.map((item) => (
                        <MenuItem key={JSON.stringify(item)} value={JSON.stringify(item)}>
                          {String(item)}
                        </MenuItem>
                      ))}
                    </Select>
                  </FormControl>
                );
              }
              const numeric = input.type === "integer" || input.type === "number";
              return (
                <TextField
                  key={name}
                  size="small"
                  label={stageLabel(name)}
                  helperText={input.description}
                  required={input.required}
                  type={numeric ? "number" : "text"}
                  value={value ?? ""}
                  onChange={(event) =>
                    setLaunchInputs((current) => ({
                      ...current,
                      [name]: event.target.value === ""
                        ? (numeric ? null : "")
                        : numeric
                          ? Number(event.target.value)
                          : event.target.value,
                    }))
                  }
                />
              );
            })}
            </Box>
            <Accordion><AccordionSummary>Advanced start settings</AccordionSummary><AccordionDetails><Box className="field-grid">
            <TextField
              size="small"
              label="Exact model (optional)"
              value={launchModel}
              onChange={(event) => setLaunchModel(event.target.value)}
              slotProps={{ htmlInput: { list: "relay-model-options" } }}
            />
            <datalist id="relay-model-options">
              {modelOptions.map((model) => <option key={model} value={model} />)}
            </datalist>
            <FormControl size="small">
              <InputLabel id="cleanup-policy">Cleanup policy</InputLabel>
              <Select
                labelId="cleanup-policy"
                value={cleanupPolicy}
                label="Cleanup policy"
                onChange={(event) => setCleanupPolicy(event.target.value)}
              >
                <MenuItem value="clean_on_success">Clean on success</MenuItem>
                <MenuItem value="retain">Retain worktree</MenuItem>
              </Select>
            </FormControl>
            <FormControl size="small">
              <InputLabel id="entry-point">Entry point</InputLabel>
              <Select
                labelId="entry-point"
                value={entryPoint}
                label="Entry point"
                onChange={(event) => setEntryPoint(event.target.value)}
              >
                <MenuItem value="">Start at roots</MenuItem>
                {(parsed.value?.entrypoints ?? []).map((entry) => (
                  <MenuItem key={entry.scope_path} value={entry.scope_path}>{entry.scope_path}</MenuItem>
                ))}
              </Select>
            </FormControl>
          </Box></AccordionDetails></Accordion>
          <Divider />
          <Stack direction="row" sx={{ justifyContent: "flex-end" }}>
            <Button
              variant="contained"
              size="large"
              onClick={() => void launch()}
              disabled={launching || promptDirty || loadedKey === null || parsed.errors.length > 0 || dirty || Object.keys(parsed.value?.nodes ?? {}).length === 0}
            >
              {launching ? "Launching…" : "Launch workflow"}
            </Button>
          </Stack>
        </Stack>
      </Paper>

      <Dialog open={handoffHelp} onClose={() => setHandoffHelp(false)} fullWidth maxWidth="md">
        <DialogTitle>Keep a report for the next stage</DialogTitle>
        <DialogContent><Stack spacing={2}>
          <Typography>Open Advanced workflow configuration and find the output that checks the file. A label selector keeps the full report and reads a named verdict line from it.</Typography>
          <Typography component="pre" className="activity-text">{'outputs:\n  verdict:\n    label:\n      artifact: REVIEW.md\n      label: Ready'}</Typography>
          <Typography>For a report containing “Ready: Yes”, this saves the report and gives the output verdict the value “Yes”. Choose the file and label used by your own report. JSON and YAML reports can use json_path or yaml_path with artifact and path fields.</Typography>
          <Typography>Add a Check a result stage after the report stage to evaluate a verdict. For a stage named report, the expression can be:</Typography>
          <Typography component="pre" className="activity-text">{'needs.report.outputs.verdict == "Yes"'}</Typography>
          <Typography>Route that check to the intended next stage. Keep a Human review stage wherever a person must approve the work; an automated verdict never answers it.</Typography>
        </Stack></DialogContent>
        <DialogActions><Button onClick={() => { setHandoffHelp(false); setAdvanced(true); }}>Open workflow configuration</Button><Button onClick={() => setHandoffHelp(false)}>Close</Button></DialogActions>
      </Dialog>
      <Dialog open={newWorkflow} onClose={() => !busy && setNewWorkflow(false)} fullWidth>
        <DialogTitle>Create a workflow</DialogTitle>
        <DialogContent><Typography sx={{ mb: 2 }}>Name the workflow, then add the stages you want Relay to run in {project.display_name}.</Typography><TextField autoFocus fullWidth label="Workflow name" value={newKey} onChange={(event) => setNewKey(event.target.value)} />{error && <Alert severity="error" sx={{ mt: 2 }}>{error}</Alert>}</DialogContent>
        <DialogActions><Button onClick={() => setNewWorkflow(false)} disabled={busy}>Cancel</Button><Button variant="contained" onClick={() => void createWorkflow()} disabled={busy || !newKey.trim()}>Create workflow</Button></DialogActions>
      </Dialog>
      <Dialog open={addingStage} onClose={() => setAddingStage(false)} fullWidth>
        <DialogTitle>Add a stage</DialogTitle><DialogContent><Stack spacing={2} sx={{ pt: 1 }}><TextField label="Stage name" value={stageName} onChange={(event) => setStageName(event.target.value)} /><FormControl><InputLabel id="new-stage-action">Stage action</InputLabel><Select labelId="new-stage-action" label="Stage action" value={stageKind} onChange={(event) => setStageKind(event.target.value)}><MenuItem value="command">Run a command</MenuItem><MenuItem value="agent">Agent work</MenuItem><MenuItem value="human_wait">Ask for human review</MenuItem></Select></FormControl><Typography color="text.secondary">The new stage starts after the previous stage. You can change that order in its settings.</Typography></Stack></DialogContent><DialogActions><Button onClick={() => setAddingStage(false)}>Cancel</Button><Button variant="contained" onClick={addNode} disabled={!stageName.trim()}>Add stage</Button></DialogActions>
      </Dialog>

      <Dialog open={formattingYaml !== null} onClose={() => setFormattingYaml(null)}>
        <DialogTitle>Save canonical YAML?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            The visual editor uses the canonical YAML document. Saving will normalize formatting, so
            comments and values remain but spacing or collection style can change. Review the editor
            before continuing.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setFormattingYaml(null)}>Cancel</Button>
          <Button
            variant="contained"
            onClick={() => formattingYaml && void persistSave(formattingYaml)}
          >
            Save canonical YAML
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
