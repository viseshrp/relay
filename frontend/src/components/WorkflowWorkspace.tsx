import {
  Alert,
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
import type { AgentsResponse, JsonScalar, WorkflowDocumentResponse, WorkflowDraft } from "../types";
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

const YamlEditor = lazy(() =>
  import("./YamlEditor").then((module) => ({ default: module.YamlEditor })),
);

const LEASE_RENEW_MS = 30_000;
const AUTOSAVE_DELAY_MS = 600;

interface WorkflowWorkspaceProps {
  onRunLaunched: (runId: string) => void;
}

function workflowPath(key: string, suffix = ""): string {
  const encoded = key
    .split("/")
    .map((part) => encodeURIComponent(part))
    .join("/");
  return `/api/workflows/${encoded}${suffix}`;
}

function scalarDefault(type: string, value: unknown): JsonScalar {
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return value;
  }
  return type === "boolean" ? false : "";
}

function createHolder(): string {
  const existing = sessionStorage.getItem("relay.editor-holder");
  if (existing) return existing;
  const holder = crypto.randomUUID();
  sessionStorage.setItem("relay.editor-holder", holder);
  return holder;
}

export function WorkflowWorkspace({ onRunLaunched }: WorkflowWorkspaceProps) {
  const holder = useRef(createHolder());
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
  const [launchInputs, setLaunchInputs] = useState<Record<string, JsonScalar>>({});
  const [launchModel, setLaunchModel] = useState("");
  const [cleanupPolicy, setCleanupPolicy] = useState("clean_on_success");
  const [entryPoint, setEntryPoint] = useState("");
  const [launching, setLaunching] = useState(false);

  const parsed = useMemo(() => parseWorkflow(yamlText), [yamlText]);
  const graph = useMemo(() => flowElements(parsed.value), [parsed.value]);
  const definition = selectedNode ? parsed.value?.nodes[selectedNode] : undefined;
  const dirty = loadedKey !== null && yamlText !== savedYaml;

  const acquireLease = useCallback(async (key: string) => {
    await api<{ lease: { expires_at: string } }>(workflowPath(key, "/lease"), {
      method: "POST",
      body: JSON.stringify({ holder: holder.current }),
    });
    setLeaseReady(true);
  }, []);

  const applyDocument = useCallback((document: WorkflowDocumentResponse) => {
    const recovered = document.draft?.yaml ?? document.yaml;
    setYamlText(recovered);
    setSavedYaml(document.yaml);
    setBaseHash(document.base_hash);
    setDraft(document.draft);
    setSelectedNode(null);
  }, []);

  const loadWorkflow = useCallback(
    async (key: string) => {
      const normalized = key.trim();
      if (!normalized) return;
      setBusy(true);
      setError(null);
      setNotice(null);
      setLeaseReady(false);
      try {
        await acquireLease(normalized);
        const document = await api<WorkflowDocumentResponse>(workflowPath(normalized));
        applyDocument(document);
        setLoadedKey(normalized);
      } catch (caught) {
        setError(errorMessage(caught));
      } finally {
        setBusy(false);
      }
    },
    [acquireLease, applyDocument],
  );

  useEffect(() => {
    void api<AgentsResponse>("/api/agents").then(setAgents).catch(() => setAgents(null));
    void loadWorkflow("workflow");
  }, [loadWorkflow]);

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
    if (!dirty || loadedKey === null || !leaseReady) return;
    const timer = window.setTimeout(() => {
      void api<{ draft: WorkflowDraft }>(workflowPath(loadedKey, "/draft"), {
        method: "POST",
        body: JSON.stringify({
          yaml: yamlText,
          base_hash: baseHash,
          holder: holder.current,
        }),
      })
        .then((response) => setDraft(response.draft))
        .catch((caught: unknown) => setError(errorMessage(caught)));
    }, AUTOSAVE_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, [baseHash, dirty, leaseReady, loadedKey, yamlText]);

  useEffect(() => {
    const definitions = parsed.value?.inputs ?? {};
    setLaunchInputs((current) =>
      Object.fromEntries(
        Object.entries(definitions).map(([name, input]) => [
          name,
          current[name] ?? scalarDefault(input.type, input.default),
        ]),
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
    const id = nextNodeId(parsed.value);
    mutate((document) => document.setIn(["nodes", id], nodeDefaults("command")));
    setSelectedNode(id);
  }

  function deleteNode() {
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
    if (selectedNode === null) return;
    const needs = definition?.needs;
    mutate((document) =>
      document.setIn(["nodes", selectedNode], {
        ...nodeDefaults(type),
        ...(needs && needs.length > 0 ? { needs } : {}),
      }),
    );
  }

  async function persistSave(canonical: string) {
    if (loadedKey === null) return;
    setBusy(true);
    setError(null);
    try {
      await api<{ ok: boolean }>(workflowPath(loadedKey, "/save"), {
        method: "POST",
        body: JSON.stringify({
          yaml: canonical,
          base_hash: baseHash,
          holder: holder.current,
        }),
      });
      const refreshed = await api<WorkflowDocumentResponse>(workflowPath(loadedKey));
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
      const response = await api<{ run_id: string }>("/api/runs", {
        method: "POST",
        body: JSON.stringify({
          workflow_key: loadedKey,
          inputs: launchInputs,
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

  return (
    <Stack spacing={2}>
      <Paper className="toolbar-card" variant="outlined">
        <Stack
          direction={{ xs: "column", md: "row" }}
          spacing={1.5}
          sx={{ alignItems: { md: "center" } }}
        >
          <TextField
            size="small"
            label="Workflow key"
            value={workflowKey}
            onChange={(event) => setWorkflowKey(event.target.value)}
            onKeyDown={(event) => {
              if (event.key === "Enter") void loadWorkflow(workflowKey);
            }}
          />
          <Button variant="outlined" onClick={() => void loadWorkflow(workflowKey)} disabled={busy}>
            Load
          </Button>
          <Button variant="contained" onClick={requestSave} disabled={!dirty || busy || !leaseReady}>
            Save
          </Button>
          <Button onClick={addNode} disabled={parsed.value === null || !leaseReady}>Add node</Button>
          <Box sx={{ flex: 1 }} />
          <Chip
            size="small"
            color={leaseReady ? "success" : "warning"}
            label={leaseReady ? "Editor lease active" : "Editor lease unavailable"}
          />
          {draft && <Chip size="small" label={`Draft ${draft.validation_state}`} />}
          {dirty && <Chip size="small" color="primary" variant="outlined" label="Unsaved" />}
        </Stack>
      </Paper>

      {error && <Alert severity="error" onClose={() => setError(null)}>{error}</Alert>}
      {notice && <Alert severity="success" onClose={() => setNotice(null)}>{notice}</Alert>}
      {parsed.errors.length > 0 && (
        <Alert severity="warning">{parsed.errors.join(" ")}</Alert>
      )}

      <Box className="author-grid">
        <Paper className="canvas-panel" variant="outlined">
          <FlowCanvas
            nodes={graph.nodes}
            edges={graph.edges}
            selectedId={selectedNode}
            onSelect={setSelectedNode}
          />
        </Paper>
        <Paper className="yaml-panel" variant="outlined">
          <Suspense fallback={<Box className="loading-panel">Loading YAML editor…</Box>}>
            <YamlEditor value={yamlText} onChange={setYamlText} />
          </Suspense>
        </Paper>
      </Box>

      {selectedNode && definition && (
        <Paper className="section-card" variant="outlined">
          <Stack spacing={2}>
            <Stack direction="row" spacing={2} sx={{ alignItems: "center" }}>
              <Typography variant="h6" sx={{ flex: 1 }}>{selectedNode}</Typography>
              <Button color="error" onClick={deleteNode}>Delete node</Button>
            </Stack>
            <Box className="field-grid">
              <FormControl size="small">
                <InputLabel>Node type</InputLabel>
                <Select
                  label="Node type"
                  value={definition.type}
                  onChange={(event) => setNodeType(event.target.value)}
                >
                  {['agent', 'command', 'human_wait', 'condition', 'loop', 'subworkflow'].map((type) => (
                    <MenuItem key={type} value={type}>{type}</MenuItem>
                  ))}
                </Select>
              </FormControl>
              <TextField
                size="small"
                label="Needs (comma separated)"
                value={(definition.needs ?? []).join(", ")}
                onChange={(event) =>
                  setNodeField(
                    "needs",
                    event.target.value.split(",").map((item) => item.trim()).filter(Boolean),
                  )
                }
              />
              {(definition.type === "agent" || definition.type === "command") && (
                <FormControlLabel
                  control={
                    <Switch
                      checked={definition.writes === true}
                      onChange={(event) => setNodeField("writes", event.target.checked)}
                    />
                  }
                  label="Writes to worktree"
                />
              )}
              {definition.type === "agent" && (
                <TextField
                  size="small"
                  label="Exact model override"
                  value={typeof definition.model === "string" ? definition.model : ""}
                  onChange={(event) => setNodeField("model", event.target.value)}
                />
              )}
              {definition.type === "command" && (
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
              )}
              {definition.type === "human_wait" && (
                <TextField
                  size="small"
                  label="Prompt"
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
          </Stack>
        </Paper>
      )}

      <Paper className="section-card" variant="outlined">
        <Stack spacing={2}>
          <Box>
            <Typography variant="h6">Launch</Typography>
            <Typography variant="body2" color="text.secondary">
              Inputs come from the loaded workflow schema. Launch still runs server-side validation.
            </Typography>
          </Box>
          <Box className="field-grid">
            {Object.entries(inputDefinitions).map(([name, input]) => {
              const value = launchInputs[name] ?? scalarDefault(input.type, input.default);
              if (input.type === "boolean") {
                return (
                  <FormControlLabel
                    key={name}
                    control={
                      <Checkbox
                        checked={value === true}
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
                    <InputLabel>{name}</InputLabel>
                    <Select
                      label={name}
                      value={JSON.stringify(value)}
                      onChange={(event) =>
                        setLaunchInputs((current) => ({
                          ...current,
                          [name]: JSON.parse(event.target.value) as JsonScalar,
                        }))
                      }
                    >
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
                  label={name}
                  helperText={input.description}
                  required={input.required}
                  type={numeric ? "number" : "text"}
                  value={value ?? ""}
                  onChange={(event) =>
                    setLaunchInputs((current) => ({
                      ...current,
                      [name]: numeric && event.target.value !== ""
                        ? Number(event.target.value)
                        : event.target.value,
                    }))
                  }
                />
              );
            })}
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
              <InputLabel>Cleanup policy</InputLabel>
              <Select
                value={cleanupPolicy}
                label="Cleanup policy"
                onChange={(event) => setCleanupPolicy(event.target.value)}
              >
                <MenuItem value="clean_on_success">Clean on success</MenuItem>
                <MenuItem value="retain">Retain worktree</MenuItem>
              </Select>
            </FormControl>
            <FormControl size="small">
              <InputLabel>Entry point</InputLabel>
              <Select
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
          </Box>
          <Divider />
          <Stack direction="row" sx={{ justifyContent: "flex-end" }}>
            <Button
              variant="contained"
              size="large"
              onClick={() => void launch()}
              disabled={launching || loadedKey === null || parsed.errors.length > 0 || dirty}
            >
              {launching ? "Launching…" : "Launch workflow"}
            </Button>
          </Stack>
        </Stack>
      </Paper>

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
