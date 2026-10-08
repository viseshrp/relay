import { HelpLabel, HelpTip, HelpTextField, HelpControl, HelpSelectField } from "./HelpTip";
import { Alert, Accordion, AccordionDetails, AccordionSummary, Box, Button, Chip, Dialog, DialogActions, DialogContent, DialogContentText, DialogTitle, FormControl, FormControlLabel, InputLabel, List, ListItemButton, ListItemText, MenuItem, Paper, Select, Stack, Switch, TextField, Typography } from "@mui/material";
import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ActionIcon } from "./ActionIcon";
import { api, errorMessage, RelayApiError } from "../api";
import { editorHolder } from "../editor-session";
import { projectPath, stageLabel } from "../navigation";
import type { AgentOptions, AgentsResponse, HandoffWarning, ProjectRecord, ProjectSettingsResponse, RepairDefaults, WorkflowDocumentResponse, WorkflowDraft } from "../types";
import { canonicalYaml, flowElements, mutateWorkflow, nextNodeId, nodeDefaults, parseWorkflow, type WorkflowNodeValue, type RepairRuleValue } from "../workflow";
import { FlowCanvas } from "./FlowCanvas";
import { AgentConfiguration } from "./AgentConfiguration";
import { PromptEditor } from "./PromptEditor";
import { ModelPicker } from "./ModelPicker";
import { RepairSettings } from "./RepairSettings";
import { ControlJobFields } from "./ControlJobFields";
import { CommandFields } from "./CommandFields";
import { EnvironmentEditor } from "./EnvironmentEditor";
import { CreateWorkflowDialog } from "./CreateWorkflowDialog";
import { LaunchPanel } from "./LaunchPanel";

const YamlEditor = lazy(() =>
  import("./YamlEditor").then((module) => ({ default: module.YamlEditor })),
);

const LEASE_RENEW_MS = 30_000;
const AUTOSAVE_DELAY_MS = 600;

interface WorkflowWorkspaceProps {
  initialCreate?: boolean;
  onRunLaunched: (runId: string) => void;
  project: ProjectRecord;
  requestProject: string | null;
  initialWorkflow: string | null;
  initialLaunch: boolean;
  onLaunchClosed: () => void;
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

export function WorkflowWorkspace({ initialCreate = false, onRunLaunched, project, requestProject, initialWorkflow, initialLaunch, onLaunchClosed, onWorkflowLoaded, onNavigationReady }: WorkflowWorkspaceProps) {
  const holder = useRef(editorHolder());
  const initialKey = useRef(initialWorkflow);
  const [inventory, setInventory] = useState<Array<{ key: string; name: string }>>([]);
  const [newWorkflow, setNewWorkflow] = useState(initialCreate);
  const [advanced, setAdvanced] = useState(false);
  const [addingStage, setAddingStage] = useState(false);
  const [stageName, setStageName] = useState("Check project");
  const [stageKind, setStageKind] = useState("command");
  const [stageWorkflow, setStageWorkflow] = useState("");
  const [warnings, setWarnings] = useState<HandoffWarning[]>([]);
  const [handoffHelp, setHandoffHelp] = useState(false);
  const [promptDirty, setPromptDirty] = useState(false);
  const [repairDraft, setRepairDraft] = useState<{ rule: RepairRuleValue; outputs: Record<string, unknown> } | null>(null);
  const repairOpen = repairDraft !== null;
  const [repairDefaults, setRepairDefaults] = useState<RepairDefaults | null>(null);
  const [workflowKey, setWorkflowKey] = useState("workflow");
  const [loadedKey, setLoadedKey] = useState<string | null>(null);
  const [yamlText, setYamlText] = useState("");
  const [savedYaml, setSavedYaml] = useState("");
  const [baseHash, setBaseHash] = useState("");
  const [draft, setDraft] = useState<WorkflowDraft | null>(null);
  const [leaseReady, setLeaseReady] = useState(false);
  const [selectedNode, setSelectedNode] = useState<string | null>(null);
  const [stageFilter, setStageFilter] = useState("");
  const [stageFocusRequest, setStageFocusRequest] = useState(0);
  const stageSettings = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!selectedNode) return;
    stageSettings.current?.scrollIntoView({ block: "start" });
    stageSettings.current?.focus({ preventScroll: true });
  }, [selectedNode, stageFocusRequest]);
  const stageCanvas = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [formattingYaml, setFormattingYaml] = useState<string | null>(null);
  const [agents, setAgents] = useState<AgentsResponse | null>(null);
  const [commands, setCommands] = useState<Record<string, string[]>>({});
  const [launchOpen, setLaunchOpen] = useState(initialLaunch);
  const launchButton = useRef<HTMLButtonElement>(null);

  const parsed = useMemo(() => parseWorkflow(yamlText), [yamlText]);
  const graph = useMemo(() => flowElements(parsed.value), [parsed.value]);
  // "verify_fixes" or "VERIFY" finds the stage labeled "Verify fixes".
  const stageQuery = stageFilter.trim().toLowerCase();
  const matchingStages = graph.nodes.filter((node) =>
    node.data.label.toLowerCase().includes(stageQuery) || node.id.toLowerCase().includes(stageQuery),
  );
  const definition = selectedNode ? parsed.value?.nodes[selectedNode] : undefined;
  const dirty = loadedKey !== null && yamlText !== savedYaml;
  const needsDraftWrite = loadedKey !== null && (draft ? draft.yaml !== yamlText : dirty);
  const draftWrites = useRef<Promise<void>>(Promise.resolve());
  const flushDraft = useCallback(async () => {
    if (promptDirty) throw new Error("Save the agent's instructions before leaving this stage.");
    if (!needsDraftWrite || loadedKey === null) return;
    if (!leaseReady) throw new Error("Save or recover this workflow before switching projects. Its editing lease is unavailable.");
    const write = draftWrites.current.catch(() => undefined).then(async () => {
      const response = await api<{ draft: WorkflowDraft }>(projectPath(workflowPath(loadedKey, "/draft"), requestProject), {
        method: "POST", body: JSON.stringify({ yaml: yamlText, base_hash: baseHash, holder: holder.current }),
      });
      setDraft(response.draft);
    });
    draftWrites.current = write;
    await write;
  }, [needsDraftWrite, loadedKey, leaseReady, requestProject, yamlText, baseHash, promptDirty]);
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
    setRepairDefaults(document.repair_defaults);
    setRepairDraft(null);
    setSelectedNode(null);
    setStageFilter("");
    setStageFocusRequest(0);
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
    let active = true;
    setCommands({});
    void api<ProjectSettingsResponse>(projectPath("/api/projects/defaults", requestProject)).then((response) => { if (active) setCommands(response.effective.workflow_defaults.commands); }).catch((caught: unknown) => { if (active) setError(errorMessage(caught)); });
    void api<AgentsResponse>(projectPath("/api/agents", requestProject)).then((response) => { if (active) setAgents(response); }).catch(() => { if (active) setAgents(null); });
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
    if (!needsDraftWrite || loadedKey === null || !leaseReady || busy) return;
    const timer = window.setTimeout(() => {
      void flushDraft().catch((caught: unknown) => setError(errorMessage(caught)));
    }, AUTOSAVE_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [needsDraftWrite, leaseReady, loadedKey, busy, flushDraft]);

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
    mutate((document, value) => {
      const next: WorkflowNodeValue = { ...nodeDefaults(stageKind), ...(previous ? { needs: [previous] } : {}) };
      if (stageKind === "condition" || stageKind === "loop") {
        const target = nextNodeId(value, `${id}_${stageKind === "loop" ? "exhausted" : "continue"}`);
        if (stageKind === "condition") next.branches = { true: target };
        else {
          next.body = { check: nodeDefaults("command") };
          next.until = "${{ loop.index >= 1 }}";
          next.exhausted = target;
        }
        document.setIn(["nodes", target], { ...nodeDefaults("command"), needs: [id] });
      }
      if (stageKind === "subworkflow") next.workflow = stageWorkflow;
      document.setIn(["nodes", id], next);
    });
    setSelectedNode(id);
    setStageFocusRequest((value) => value + 1);
    setAddingStage(false);
  }

  function selectStage(id: string, bringIntoView = false) {
    if (promptDirty) { setError("Save the agent's instructions before selecting another stage."); return; }
    setSelectedNode(id);
    // Selecting the same stage again restores its readable scale after panning.
    setStageFocusRequest((value) => value + 1);
    if (bringIntoView) {
      stageCanvas.current?.scrollIntoView({ block: "center" });
      stageCanvas.current?.focus({ preventScroll: true });
    }
  }

  function deleteNode() {
    if (promptDirty) { setError("Save the agent's instructions before removing a stage."); return; }
    if (selectedNode === null) return;
    mutate((document, value) => {
      document.deleteIn(["nodes", selectedNode]);
      if (document.hasIn(["repairs", selectedNode])) document.deleteIn(["repairs", selectedNode]);
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
    mutate((document) => {
      document.setIn(["nodes", selectedNode], {
        ...nodeDefaults(type),
        ...(needs && needs.length > 0 ? { needs } : {}),
      });
      if (!["agent", "command"].includes(type) && document.hasIn(["repairs", selectedNode])) document.deleteIn(["repairs", selectedNode]);
    });
  }

  async function discardChanges() {
    if (!loadedKey || !leaseReady || promptDirty) return;
    setBusy(true);
    setError(null);
    try {
      await draftWrites.current.catch(() => undefined);
      const response = await api<{ draft: WorkflowDraft }>(projectPath(workflowPath(loadedKey, "/draft"), requestProject), {
        method: "POST", body: JSON.stringify({ yaml: savedYaml, base_hash: baseHash, holder: holder.current }),
      });
      setDraft(response.draft);
      setYamlText(savedYaml);
      setRepairDraft(null);
      setSelectedNode(null);
      setNotice("Changes discarded. The saved workflow is unchanged.");
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  function openRepairs() {
    if (promptDirty) { setError("Save the stage instructions before opening repairs."); return; }
    if (!selectedNode || !definition || !repairDefaults) return;
    const outputs = definition.outputs && typeof definition.outputs === "object" ? definition.outputs : {};
    const acceptedOutput = Object.keys(outputs)[0] ?? "ready";
    const existing = parsed.value?.repairs?.[selectedNode];
    const rule: RepairRuleValue = existing ?? { enabled: false, accepted_output: acceptedOutput, accepted_value: "Yes", fix: {
      type: "agent", writes: true, model: definition.model, agents: definition.agents,
      agent_options: definition.agent_options,
    }, verify: {
      type: "agent", writes: true, allow_no_commit: true, model: definition.model,
      agents: definition.agents, agent_options: definition.agent_options,
      outputs: { [acceptedOutput]: { label: { artifact: "REVIEW_FIX_VERIFICATION.md", label: "Ready" } } },
    } };
    setRepairDraft({ rule, outputs: existing || Object.keys(outputs).length ? outputs : {
      [acceptedOutput]: { label: { artifact: "REVIEW.md", label: "Ready" } },
    } });
  }

  function applyRepairs() {
    if (!selectedNode || !repairDraft || promptDirty) return;
    const existing = parsed.value?.repairs?.[selectedNode];
    const outputs = definition?.outputs ?? {};
    if ((!existing && repairDraft.rule.enabled === false) ||
        (JSON.stringify(existing) === JSON.stringify(repairDraft.rule) &&
         JSON.stringify(outputs) === JSON.stringify(repairDraft.outputs))) {
      setRepairDraft(null);
      return;
    }
    mutate((document) => {
      document.setIn(["repairs", selectedNode], repairDraft.rule);
      if (JSON.stringify(outputs) !== JSON.stringify(repairDraft.outputs)) {
        document.setIn(["nodes", selectedNode, "outputs"], repairDraft.outputs);
      }
    });
    setRepairDraft(null);
  }

  function setAgentOption(agentId: string, field: keyof AgentOptions, value: string | null) {
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
      setInventory((items) => items.map((item) => item.key === loadedKey
        ? { ...item, name: parseWorkflow(refreshed.yaml).value?.name || item.name }
        : item));
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

  const modelOptions = Array.from(
    new Set(agents?.agents.flatMap((agent) => agent.models.map((model) => model.value)) ?? []),
  ).sort();
  const candidateIds = Array.from(new Set([
    ...(definition?.agents ?? []),
    ...(parsed.value?.agents ?? []),
    ...(agents?.preferences ?? []),
  ]));
  const effectiveModel = (typeof definition?.model === "string" ? definition.model : "")
    || parsed.value?.model || agents?.defaults?.model
    || agents?.defaults?.providers[candidateIds[0] ?? ""]?.model || "";

  return (
    <Box className="workflow-author-layout">
      <Box component="nav" aria-label="Workflow sidebar" data-tour="workflows" className="actions-sidebar">
        <Typography variant="h6" sx={{ p: 1 }}>Workflows</Typography>
        <Button fullWidth variant="outlined" onClick={() => setNewWorkflow(true)}>New workflow</Button>
        <List>{inventory.map((item) => <ListItemButton key={item.key} selected={item.key === loadedKey} disabled={busy} onClick={() => void loadWorkflow(item.key)}><ActionIcon name="workflow" /><ListItemText title={item.name} primary={item.name} /></ListItemButton>)}</List>
      </Box>
      <Stack spacing={2} sx={{ minWidth: 0 }}>
      <Stack component="header" role="region" aria-label="Workflow header" direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ alignItems: { xs: "stretch", sm: "center" }, justifyContent: "space-between" }}>
        <Box>
          <Typography component="h1" variant="h5">{parsed.value?.name || "Choose a workflow"}</Typography>
          <Typography variant="body2" color="text.secondary">{loadedKey}</Typography>
        </Box>
        <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}><Button ref={launchButton} data-tour="launch" variant="contained" disabled={loadedKey === null || busy} onClick={() => { setError(null); setLaunchOpen(true); }}>Run workflow</Button><HelpTip topic="launch" /></Stack>
      </Stack>
      {loadedKey === null && <Paper className="section-card" variant="outlined">
        <Typography variant="h6">{busy ? "Loading workflow…" : inventory.length ? "Choose a workflow" : "No workflows yet"}</Typography>
        <Typography color="text.secondary">{inventory.length ? "Select a workflow in the sidebar." : "Create a workflow to add jobs and start a run."}</Typography>
        <Button onClick={() => setNewWorkflow(true)}>New workflow</Button>
      </Paper>}
      {loadedKey !== null && <Paper className="toolbar-card" variant="outlined">
        <Stack
          direction={{ xs: "column", md: "row" }}
          spacing={1.5}
          useFlexGap sx={{ alignItems: { md: "center" }, flexWrap: "wrap" }}
        >
          <FormControl size="small" className="workflow-picker">
            <InputLabel id="workflow-picker" shrink>Workflow</InputLabel>
            <Select displayEmpty renderValue={!inventory.some((item) => item.key === loadedKey) ? () => "Choose a workflow" : undefined} labelId="workflow-picker" label="Workflow" value={inventory.some((item) => item.key === loadedKey) ? loadedKey ?? "" : ""} onChange={(event) => void loadWorkflow(event.target.value)} disabled={busy}>
              {inventory.map((item) => <MenuItem key={item.key} value={item.key}>{item.name}</MenuItem>)}
            </Select>
          </FormControl>
          <HelpControl topic="save"><Button variant="contained" onClick={requestSave} disabled={!dirty || busy || !leaseReady}>
            Save
          </Button></HelpControl>
          <Button onClick={() => void discardChanges()} disabled={!dirty || busy || !leaseReady || promptDirty}>Discard changes</Button>
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
      </Paper>}

      {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}
      {notice && <Alert severity="success" onClose={() => setNotice(null)}>{notice}</Alert>}
      {warnings.map((warning) => <Alert key={`${warning.workflow_key ?? ""}-${warning.scope_path}-${warning.output}`} severity="warning" action={<Button onClick={() => setHandoffHelp(true)}>Retain the report</Button>}>
        {warning.workflow_key ? `${warning.workflow_key} · ` : ""}{stageLabel(warning.scope_path)}: {warning.artifact} is only checked for existence. {warning.message}
      </Alert>)}
      {loadedKey && Object.keys(parsed.value?.nodes ?? {}).length === 0 && <Alert severity="info" action={<Button onClick={() => setAddingStage(true)}>Add first stage</Button>}>Your workflow is empty. Add a command, agent task, or review step to begin.</Alert>}
      {loadedKey !== null && parsed.errors.length > 0 && (
        <Alert severity="warning">{parsed.errors.join(" ")}</Alert>
      )}

      {loadedKey !== null && <Box>
        <Paper className="canvas-panel" variant="outlined">
          <Box sx={{ p: 2 }}>
            <Typography variant="subtitle2"><HelpLabel topic="stages">Workflow stages</HelpLabel></Typography>
            <Typography variant="body2" color="text.secondary">Choose a stage to center it and edit its settings below.</Typography>
          </Box>
          <Stack direction={{ xs: "column", md: "row" }}>
            <Box component="nav" aria-label="Workflow stage navigation" sx={{ width: { md: 260 }, flexShrink: 0, p: 1.5 }}>
              <TextField fullWidth size="small" label="Find a stage" value={stageFilter} onChange={(event) => setStageFilter(event.target.value)} />
              <List sx={{ maxHeight: { xs: 210, md: 490 }, overflowY: "auto", mt: 1 }}>
                {matchingStages.map((node) => <ListItemButton key={node.id} component="button" selected={selectedNode === node.id} aria-pressed={selectedNode === node.id} onClick={() => selectStage(node.id, true)} sx={{ width: "100%", textAlign: "left" }}>
                  <ListItemText title={node.data.label} primary={node.data.label} secondary={parsed.value?.repairs?.[node.id]?.enabled !== false && parsed.value?.repairs?.[node.id] ? "Automatic repairs configured" : undefined} />
                </ListItemButton>)}
              </List>
              {matchingStages.length === 0 && graph.nodes.length > 0 && <Typography variant="body2" sx={{ p: 1 }}>No stages match. Try another name.</Typography>}
            </Box>
            <Box ref={stageCanvas} role="region" aria-label="Workflow canvas" tabIndex={-1} sx={{ flex: 1, minWidth: 0 }}>
              <FlowCanvas
                key={`${project.id}:${loadedKey}`}
                nodes={graph.nodes}
                edges={graph.edges}
                selectedId={selectedNode}
                initialFocusId={graph.nodes[0]?.id}
                focusRequest={stageFocusRequest}
                onSelect={selectStage}
              />
            </Box>
          </Stack>
        </Paper>
        <Accordion expanded={advanced} onChange={(_event, open) => setAdvanced(open)}>
          <AccordionSummary expandIcon={<ActionIcon name="down" />}><Typography>Advanced workflow settings and YAML</Typography></AccordionSummary>
          <AccordionDetails>
          <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
            <HelpTextField topic="workflowKey" label="Workflow key" size="small" value={workflowKey} onChange={(event) => setWorkflowKey(event.target.value)} />
            <Button onClick={() => void loadWorkflow(workflowKey)}>Load</Button>
          </Stack>
          <Stack component="section" aria-label="Workflow environment" spacing={1} sx={{ mb: 2 }}>
            <Typography variant="h6">Workflow environment variables</Typography>
            <HelpControl topic="environment"><FormControlLabel label={<span>Use project and global environment variables</span>} control={<Switch checked={parsed.value?.inherit_env !== false} disabled={!leaseReady || parsed.value === null} onChange={(_event, checked) => mutate((document) => document.setIn(["inherit_env"], checked))} />} /></HelpControl>
            <Typography variant="body2" color="text.secondary">These variables apply to this workflow's command jobs. Child workflows keep their own workflow variables.</Typography>
            <EnvironmentEditor value={parsed.value?.env ?? {}} disabled={!leaseReady || parsed.value === null} onChange={(env) => mutate((document) => document.setIn(["env"], env))} />
          </Stack>
          <HelpControl topic="recovery"><FormControlLabel control={<Switch checked={parsed.value?.recovery?.enabled === true}
            disabled={!leaseReady || parsed.value === null}
            onChange={(event) => mutate((document) => document.setIn(["recovery", "enabled"], event.target.checked))} />}
            label={<span>Automatic recovery</span>} /></HelpControl>
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            Retry eligible agent failures using the workflow's retry limit, with the same model and original instructions.
            Unsafe failures and exhausted retries stop for your review.
          </Typography>
          <Box className="yaml-panel">
          <Suspense fallback={<Box className="loading-panel">Loading YAML editor…</Box>}>
            <YamlEditor value={yamlText} onChange={setYamlText} />
          </Suspense>
          </Box>
          </AccordionDetails>
        </Accordion>
      </Box>}

      {selectedNode && definition && (
        <Paper ref={stageSettings} tabIndex={-1} className="section-card stage-settings" variant="outlined" role="region" aria-label="Stage settings">
          <Stack spacing={2}>
            <Stack direction="row" spacing={2} useFlexGap sx={{ alignItems: "center", flexWrap: "wrap" }}>
              <Typography variant="h6" sx={{ flex: 1 }}>{stageLabel(selectedNode)}</Typography>
              <Button color="error" onClick={deleteNode}>Remove stage</Button>
              {["agent", "command"].includes(definition.type) && <Button variant="outlined" disabled={!leaseReady || promptDirty || !repairDefaults} onClick={openRepairs}>Repairs</Button>}
            </Stack>
            <Box className="field-grid">
              <HelpSelectField topic="stageType" label="What this stage does" size="small" value={definition.type} onChange={(event) => setNodeType(event.target.value)}>
                  {['agent', 'command', 'human_wait', 'condition', 'loop', 'subworkflow'].map((type) => (
                    <MenuItem key={type} value={type}>{{ agent: "Agent work", command: "Run a command", human_wait: "Human review", condition: "Check a result", loop: "Repeat stages", subworkflow: "Run another workflow" }[type]}</MenuItem>
                  ))}
                </HelpSelectField>
              <HelpSelectField topic="dependencies" label="Start after" placeholder="No dependencies" size="small" multiple value={definition.needs ?? []} onChange={(event) => setNodeField("needs", event.target.value)} renderValue={(items) => items.map(stageLabel).join(", ")}>
                  {Object.keys(parsed.value?.nodes ?? {}).filter((id) => id !== selectedNode).map((id) => <MenuItem key={id} value={id}>{stageLabel(id)}</MenuItem>)}
                </HelpSelectField>
              {(definition.type === "agent" || definition.type === "command") && (
                <HelpControl topic="writes"><FormControlLabel
                  control={
                    <Switch
                      checked={definition.writes === true}
                      onChange={(event) => setNodeField("writes", event.target.checked)}
                    />
                  }
                  label={<span>Allow file changes</span>}
                /></HelpControl>
              )}
              {definition.type === "agent" && (
                <>
                  <HelpControl topic="autoRetry"><FormControlLabel
                    control={<Switch checked={definition.auto_retry !== false}
                      onChange={(event) => setNodeField("auto_retry", event.target.checked)} />}
                    label={<span>Allow automatic retries for this step</span>}
                  /></HelpControl>
                  <ModelPicker key={`${selectedNode}-${candidateIds.join(",")}`} agents={agents?.agents.filter((agent) => candidateIds.includes(agent.id)) ?? []} value={typeof definition.model === "string" ? definition.model : ""} project={requestProject} onChange={setAgentModel} />
                  <HelpTextField topic="model" label="Exact model override" size="small" helperText="Choose a model offered by the selected tool. Leave empty to use the workflow's model." value={typeof definition.model === "string" ? definition.model : ""} onChange={(event) => setAgentModel(event.target.value)} slotProps={{ htmlInput: { list: "relay-model-options" } }} />
                  <HelpSelectField topic="agentOrder" label="Agent tools" size="small" multiple displayEmpty renderValue={(selected) => selected.length === 0 ? "Workflow and owner preferences"
                        : selected.map((id) => agents?.agents.find((agent) => agent.id === id)?.display_name ?? id).join(", ")} value={definition.agents ?? []} onChange={(event) => setNodeField("agents", event.target.value)}>
                      {agents?.agents.map((agent) => <MenuItem key={agent.id} value={agent.id}>{agent.display_name}</MenuItem>)}
                    </HelpSelectField>
                </>
              )}
              {definition.type === "command" && <CommandFields key={selectedNode} node={definition} commands={commands} disabled={!leaseReady || busy} onChange={(next) => {
                const key = selectedNode;
                if (key === null) return;
                mutate((document) => {
                  for (const field of ["run", "env", "inherit_env"] as const) {
                    if (next[field] === undefined) document.deleteIn(["nodes", key, field]);
                    else document.setIn(["nodes", key, field], next[field]);
                  }
                });
              }} />}
              {definition.type === "human_wait" && (
                <HelpTextField topic="humanReview" label="Review instructions and expected response" size="small" multiline minRows={4} maxRows={8} value={typeof definition.prompt === "string" ? definition.prompt : ""} onChange={(event) => setNodeField("prompt", event.target.value)} />
              )}
              {["condition", "loop"].includes(definition.type) && <ControlJobFields node={definition}
                targets={Object.keys(parsed.value?.nodes ?? {}).filter((id) => id !== selectedNode)}
                onChange={(next) => mutate((document) => document.setIn(["nodes", selectedNode], next))} />}
              {definition.type === "subworkflow" && (
                <HelpTextField topic="subworkflow" width="wide" label="Workflow key" size="small" value={typeof definition.workflow === "string" ? definition.workflow : ""} onChange={(event) => setNodeField("workflow", event.target.value)} />
              )}
            </Box>
            {definition.type === "agent" && loadedKey && selectedNode && !repairOpen && (
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
                  inheritDefaults={Boolean(effectiveModel && agents?.defaults?.providers[agentId]?.model === effectiveModel)}
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

      {repairDraft && selectedNode && loadedKey && repairDefaults && parsed.value && <RepairSettings
        stage={selectedNode} rule={repairDraft.rule} defaults={repairDefaults}
        sourceOutputs={repairDraft.outputs}
        onSourceOutput={(output, selector) => setRepairDraft((current) => current ? { ...current, outputs: { ...current.outputs, [output]: selector } } : null)}
        agents={agents} commands={commands} model={typeof parsed.value.model === "string" ? parsed.value.model : ""}
        preferences={parsed.value.agents?.length ? parsed.value.agents : agents?.preferences ?? []}
        workflowPath={workflowPath(loadedKey)} workflowKey={loadedKey} project={requestProject}
        holder={holder.current} disabled={!leaseReady} onDirty={setPromptDirty}
        onChange={(rule) => setRepairDraft((current) => current ? { ...current, rule } : null)}
        onApply={applyRepairs} onClose={() => setRepairDraft(null)} />}

      <LaunchPanel key={`${project.id}:${loadedKey}`} open={launchOpen} workflowKey={loadedKey}
        workflow={parsed.value} project={project} requestProject={requestProject} modelOptions={modelOptions} previousRun={null}
        blockedReason={busy ? "Wait for the current workflow operation to finish."
          : loadedKey === null ? "Choose or create a workflow first."
          : promptDirty ? "Save the job's instructions in the editor first."
          : parsed.errors.length > 0 ? "Fix the YAML errors in the editor before running this workflow."
          : dirty ? (leaseReady ? "Save your changes first." : "This browser cannot save your changes. Restore its editing access before running.")
          : graph.nodes.length === 0 ? "Add a job to this empty workflow before running it." : null}
        saveError={error} onSave={dirty && leaseReady && !busy && !promptDirty && parsed.errors.length === 0 ? requestSave : undefined}
        onClose={() => { setLaunchOpen(false); onLaunchClosed(); }}
        onExited={() => launchButton.current?.focus()} onRunLaunched={onRunLaunched} />

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
      <CreateWorkflowDialog open={newWorkflow} requestProject={requestProject} holder={holder.current}
        onClose={() => setNewWorkflow(false)} onCreated={async (key) => {
          const refreshed = await api<{ workflows: Array<{ key: string; name: string }> }>(projectPath("/api/workflows", requestProject));
          setInventory(refreshed.workflows);
          await loadWorkflow(key);
        }} />
      <Dialog open={addingStage} onClose={() => setAddingStage(false)} fullWidth>
        <DialogTitle>Add a stage</DialogTitle><DialogContent><Stack spacing={2} sx={{ pt: 1 }}><TextField sx={{ width: 320, maxWidth: "100%" }} label="Stage name" value={stageName} onChange={(event) => setStageName(event.target.value)} /><FormControl sx={{ width: 320, maxWidth: "100%" }}><InputLabel id="new-stage-action">Stage action</InputLabel><Select labelId="new-stage-action" label="Stage action" value={stageKind} onChange={(event) => setStageKind(event.target.value)}><MenuItem value="command">Run a command</MenuItem><MenuItem value="agent">Agent work</MenuItem><MenuItem value="human_wait">Ask for human review</MenuItem><MenuItem value="condition">Check a result</MenuItem><MenuItem value="loop">Repeat stages</MenuItem><MenuItem value="subworkflow">Run another workflow</MenuItem></Select></FormControl>
          {stageKind === "subworkflow" && <FormControl><InputLabel id="new-stage-workflow" shrink>Workflow to run</InputLabel><Select displayEmpty renderValue={stageWorkflow === "" ? () => "Choose a workflow" : undefined} labelId="new-stage-workflow" label="Workflow to run" value={stageWorkflow} onChange={(event) => setStageWorkflow(event.target.value)}>{inventory.filter((item) => item.key !== loadedKey).map((item) => <MenuItem key={item.key} value={item.key}>{item.name}</MenuItem>)}</Select><Typography variant="caption">Create another workflow first if this list is empty.</Typography></FormControl>}<Typography color="text.secondary">The new stage starts after the previous stage. You can change that order in its settings.</Typography></Stack></DialogContent><DialogActions><Button onClick={() => setAddingStage(false)}>Cancel</Button><Button variant="contained" onClick={addNode} disabled={!stageName.trim() || (stageKind === "subworkflow" && !inventory.some((item) => item.key === stageWorkflow && item.key !== loadedKey))}>Add stage</Button></DialogActions>
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
    </Box>
  );
}
