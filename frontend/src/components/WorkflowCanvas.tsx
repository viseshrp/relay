import {
  Alert,
  Box,
  Button,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";

import { editActions, parseActions } from "../actions-workflow";

import { FlowCanvas } from "./FlowCanvas";
import { YamlEditor } from "./YamlEditor";

import type { ActionsWorkflowWorkspaceState } from "./useActionsWorkflowWorkspace";
export function WorkflowCanvas({
  state,
}: {
  state: ActionsWorkflowWorkspaceState;
}) {
  const {
    mode,
    valid,
    lastValid,
    key,
    focusRequest,
    jobId,
    graph,
    addJob,
    setJobId,
    setDrawer,
    setContextMenu,
    parsed,
    change,
    text,
    setText,
    search,
    setSearch,
    matchingJobs,
    setFocusRequest,
    newKind,
    setNewKind,
    manifest,
    diagnostics,
    events,
    triggerRows,
    toggleTrigger,
    setActivation,
  } = state;
  return (
    <Box
      sx={{
        display: "grid",
        gridTemplateColumns: {
          xs: "minmax(0, 1fr)",
          lg:
            mode === "Split"
              ? "minmax(0, 1fr) minmax(0, 1fr)"
              : "minmax(0, 1fr)",
        },
        gap: 2,
      }}
    >
      {mode !== "YAML" && (
        <Paper sx={{ p: 2 }}>
          <Stack spacing={2}>
            <Typography component="h2" variant="h6">
              Jobs and ordered steps
            </Typography>
            {!valid && lastValid && (
              <Alert severity="info">Showing the last valid version</Alert>
            )}
            <Box sx={{ opacity: !valid && lastValid ? 0.6 : 1 }}>
              <FlowCanvas
                key={key}
                focusRequest={focusRequest}
                selectedId={jobId || undefined}
                initialFocusId={graph.nodes[0]?.id}
                followSelection
                nodes={graph.nodes}
                edges={graph.edges.map((edge) => ({
                  ...edge,
                  type: "insertJob",
                  data: { onInsert: addJob },
                }))}
                onSelect={(id) => {
                  setJobId(id);
                  setDrawer(true);
                }}
                onContextMenu={(id, x, y) => setContextMenu({ id, x, y })}
                onConnect={(connection) => {
                  if (
                    !connection.source ||
                    !connection.target ||
                    connection.source === connection.target
                  )
                    return;
                  const job = parsed.value?.jobs[connection.target];
                  const needs =
                    typeof job?.needs === "string"
                      ? [job.needs]
                      : (job?.needs ?? []);
                  change(
                    ["jobs", connection.target, "needs"],
                    [...new Set([...needs, connection.source])],
                  );
                }}
                onDeleteEdges={(edges) => {
                  let next = text;
                  for (const edge of edges) {
                    const job = parseActions(next).value?.jobs[edge.target];
                    const needs =
                      typeof job?.needs === "string"
                        ? [job.needs]
                        : (job?.needs ?? []);
                    next = editActions(
                      next,
                      ["jobs", edge.target, "needs"],
                      needs.filter((item) => item !== edge.source),
                    );
                  }
                  setText(next);
                }}
              />
            </Box>
            <Stack component="nav" aria-label="Workflow job navigation">
              <TextField
                disabled={!parsed.value}
                label="Find a job"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
              {matchingJobs.map(([id, item]) => (
                <Button
                  key={id}
                  aria-pressed={jobId === id}
                  onClick={() => {
                    setJobId(id);
                    setDrawer(true);
                    setFocusRequest((value) => value + 1);
                  }}
                >
                  {item.name ||
                    id
                      .replace(/_/g, " ")
                      .replace(/^./, (letter) => letter.toUpperCase())}
                </Button>
              ))}
              {!matchingJobs.length && search && (
                <Typography>No jobs match. Try another name.</Typography>
              )}
            </Stack>
            <TextField
              select
              label="New job type"
              value={newKind}
              onChange={(event) => setNewKind(event.target.value)}
            >
              <MenuItem value="script">Run a script</MenuItem>
              {manifest?.builtins.map((kind) => (
                <MenuItem value={kind} key={kind}>
                  {kind.replace("relay/", "").replace("@v1", "")}
                </MenuItem>
              ))}
            </TextField>
            <Button disabled={!parsed.value} onClick={() => addJob()}>
              Add job
            </Button>
          </Stack>
        </Paper>
      )}
      {mode !== "Visual" && (
        <Paper sx={{ p: 2 }}>
          <Typography component="h2" variant="h6">
            Workflow YAML
          </Typography>
          <YamlEditor
            value={text}
            onChange={setText}
            manifest={manifest}
            diagnostics={diagnostics}
          />
          {events
            .filter((event) =>
              [
                "schedule",
                "push",
                "workflow_run",
                "repository_dispatch",
              ].includes(event),
            )
            .map((event) => {
              const enabled = triggerRows.some(
                (row) =>
                  row.workflow_key === key &&
                  row.event === event &&
                  row.enabled,
              );
              return (
                <Button
                  key={event}
                  onClick={() =>
                    enabled
                      ? void toggleTrigger(event, false)
                      : setActivation(event)
                  }
                >
                  {enabled ? "Disable" : "Activate"} {event}
                </Button>
              );
            })}
        </Paper>
      )}
    </Box>
  );
}
