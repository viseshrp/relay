import {
  Alert,
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  FormControl,
  FormControlLabel,
  InputLabel,
  List,
  ListItemButton,
  ListItemText,
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
import { editorHolder } from "../editor-session";
import { projectPath, stageLabel } from "../navigation";
import type { AgentOptions, AgentsResponse, HandoffWarning, ProjectRecord, RepairDefaults, WorkflowDocumentResponse, WorkflowDraft } from "../types";
import {
  canonicalYaml,
  flowElements,
  mutateWorkflow,
  nextNodeId,
  nodeDefaults,
  parseWorkflow,
  type WorkflowNodeValue,
  type RepairRuleValue,
} from "../workflow";
import { FlowCanvas } from "./FlowCanvas";
import { AgentConfiguration } from "./AgentConfiguration";
import { PromptEditor } from "./PromptEditor";
import { ModelPicker } from "./ModelPicker";
import { RepairSettings } from "./RepairSettings";
import { CreateWorkflowDialog } from "./CreateWorkflowDialog";
import { LaunchPanel } from "./LaunchPanel";

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

export function WorkflowWorkspace({ onRunLaunched, project, requestProject, initialWorkflow, initialLaunch, onLaunchClosed, onWorkflowLoaded, onNavigationReady }: WorkflowWorkspaceProps) {
  const holder = useRef(editorHolder());
  const initialKey = useRef(initialWorkflow);
  const [inventory, setInventory] = useState<Array<{ key: string; name: string }>>([]);
  const [newWorkflow, setNewWorkflow] = useState(false);
  const [advanced, setAdvanced] = useState(false);
  const [addingStage, setAddingStage] = useState(false);
  const [stageName, setStageName] = useState("Check project");
  const [stageKind, setStageKind] = useState("command");
  const [warnings, setWarnings] = useState<HandoffWarning[]>([]);
  const [handoffHelp, setHandoffHelp] = useState(false);
  const [promptDirty, setPromptDirty] = useState(false);
  const [repairOpen, setRepairOpen] = useState(false);
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
  const stageCanvas = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [formattingYaml, setFormattingYaml] = useState<string | null>(null);
  const [agents, setAgents] = useState<AgentsResponse | null>(null);
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
    setRepairDefaults(document.repair_defaults);
    setRepairOpen(false);
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
      document.deleteIn(["repairs", selectedNode]);
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
      if (!["agent", "command"].includes(type)) document.deleteIn(["repairs", selectedNode]);
    });
  }

  function setRepairs(rule: RepairRuleValue) {
    if (selectedNode === null) return;
    mutate((document) => document.setIn(["repairs", selectedNode], rule));
  }

  function openRepairs() {
    if (promptDirty) { setError("Save the stage instructions before opening repairs."); return; }
    if (!selectedNode || !definition || !repairDefaults) return;
    if (!parsed.value?.repairs?.[selectedNode]) {
      const outputs = definition.outputs && typeof definition.outputs === "object" ? definition.outputs : {};
      const acceptedOutput = Object.keys(outputs)[0] ?? "ready";
      const rule = { accepted_output: acceptedOutput, accepted_value: "Yes", fix: {
        type: "agent", writes: true, model: definition.model, agents: definition.agents,
        agent_options: definition.agent_options,
      }, verify: {
        type: "agent", writes: true, allow_no_commit: true, model: definition.model,
        agents: definition.agents, agent_options: definition.agent_options,
        outputs: { [acceptedOutput]: { label: { artifact: "REVIEW_FIX_VERIFICATION.md", label: "Ready" } } },
      } };
      mutate((document) => {
        document.setIn(["repairs", selectedNode], rule);
        if (!Object.keys(outputs).length) document.setIn(["nodes", selectedNode, "outputs", acceptedOutput], { label: { artifact: "REVIEW.md", label: "Ready" } });
      });
    }
    setRepairOpen(true);
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

  const modelOptions = Array.from(
    new Set(agents?.agents.flatMap((agent) => agent.models.map((model) => model.value)) ?? []),
  ).sort();
  const candidateIds = Array.from(new Set([
    ...(definition?.agents ?? []),
    ...(parsed.value?.agents ?? []),
    ...(agents?.preferences ?? []),
  ]));
  const effectiveModel = (typeof definition?.model === "string" ? definition.model : "")
    || parsed.value?.model || "";

  return (
    <Stack spacing={2}>
      <Stack component="header" role="region" aria-label="Workflow header" direction="row" spacing={2} sx={{ alignItems: "center", justifyContent: "space-between" }}>
        <Box>
          <Typography variant="h4">{parsed.value?.name || "Choose a workflow"}</Typography>
          <Typography color="text.secondary">Choose a workflow, edit its jobs, and save your changes.</Typography>
        </Box>
        <Button ref={launchButton} variant="contained" onClick={() => { setError(null); setLaunchOpen(true); }}>Run workflow</Button>
      </Stack>
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
          <Box sx={{ p: 2 }}>
            <Typography variant="subtitle2">Workflow stages</Typography>
            <Typography variant="body2" color="text.secondary">Choose a stage to center it and edit its settings below.</Typography>
          </Box>
          <Stack direction={{ xs: "column", md: "row" }}>
            <Box component="nav" aria-label="Workflow stage navigation" sx={{ width: { md: 260 }, flexShrink: 0, p: 1.5 }}>
              <TextField fullWidth size="small" label="Find a stage" value={stageFilter} onChange={(event) => setStageFilter(event.target.value)} />
              <List sx={{ maxHeight: { xs: 210, md: 490 }, overflowY: "auto", mt: 1 }}>
                {matchingStages.map((node) => <ListItemButton key={node.id} component="button" selected={selectedNode === node.id} aria-pressed={selectedNode === node.id} onClick={() => selectStage(node.id, true)} sx={{ width: "100%", textAlign: "left" }}>
                  <ListItemText primary={node.data.label} secondary={parsed.value?.repairs?.[node.id]?.enabled !== false && parsed.value?.repairs?.[node.id] ? "Automatic repairs configured" : undefined} />
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
          <AccordionSummary><Typography>Advanced workflow settings and YAML</Typography></AccordionSummary>
          <AccordionDetails>
          <Stack direction="row" spacing={1} sx={{ mb: 2 }}>
            <TextField size="small" label="Workflow key" value={workflowKey} onChange={(event) => setWorkflowKey(event.target.value)} />
            <Button onClick={() => void loadWorkflow(workflowKey)}>Load</Button>
          </Stack>
          <FormControlLabel control={<Switch checked={parsed.value?.recovery?.enabled === true}
            disabled={!leaseReady || parsed.value === null}
            onChange={(event) => mutate((document) => document.setIn(["recovery", "enabled"], event.target.checked))} />}
            label="Automatic recovery" />
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
      </Box>

      {selectedNode && definition && (
        <Paper className="section-card" variant="outlined" role="region" aria-label="Stage settings">
          <Stack spacing={2}>
            <Stack direction="row" spacing={2} sx={{ alignItems: "center" }}>
              <Typography variant="h6" sx={{ flex: 1 }}>{stageLabel(selectedNode)}</Typography>
              <Button color="error" onClick={deleteNode}>Remove stage</Button>
              {["agent", "command"].includes(definition.type) && <Button variant="outlined" disabled={!leaseReady || promptDirty || !repairDefaults} onClick={openRepairs}>Repairs</Button>}
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

      {repairOpen && selectedNode && loadedKey && repairDefaults && parsed.value?.repairs?.[selectedNode] && <RepairSettings
        stage={selectedNode} rule={parsed.value.repairs[selectedNode]} defaults={repairDefaults}
        sourceOutputs={definition?.outputs && typeof definition.outputs === "object" ? definition.outputs : {}}
        onSourceOutput={(output, selector) => mutate((document) => document.setIn(["nodes", selectedNode, "outputs", output], selector))}
        agents={agents} model={typeof parsed.value.model === "string" ? parsed.value.model : ""}
        preferences={parsed.value.agents?.length ? parsed.value.agents : agents?.preferences ?? []}
        workflowPath={workflowPath(loadedKey)} workflowKey={loadedKey} project={requestProject}
        holder={holder.current} disabled={!leaseReady} onDirty={setPromptDirty}
        onChange={setRepairs} onClose={() => setRepairOpen(false)} />}

      <LaunchPanel key={`${project.id}:${loadedKey}`} open={launchOpen} workflowKey={loadedKey}
        workflow={parsed.value} project={project} requestProject={requestProject} modelOptions={modelOptions}
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
