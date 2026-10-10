import { ViewSkeleton } from "./ViewSkeleton";
import { relativeTime } from "../count";
import {
  Alert,
  Box,
  Button,
  Chip,
  FormControl,
  InputLabel,
  List,
  ListItem,
  ListItemButton,
  MenuItem,
  Paper,
  Select,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useResource } from "../useResource";
import { jobDuration } from "../job";
import { projectPath, stageLabel, statusLabel, viewHref } from "../navigation";
import type { ProjectRecord, RunSummary } from "../types";
import { useClock } from "../useClock";
import { ActionIcon, StatusIcon } from "./ActionIcon";
import { WorkflowSidebar, type WorkflowEntry } from "./WorkflowSidebar";

interface HistoryFilters {
  workflow: string;
  status: string;
  branch: string;
  query: string;
}
export function RunHistory({
  project,
  runs,
  waitingRuns,
  more,
  refreshing,
  loading = false,
  onMore,
  onSelect,
  onRefresh,
  onRunWorkflow,
  onEditWorkflow,
  filters,
  onFilters,
}: {
  project: ProjectRecord;
  runs: RunSummary[];
  waitingRuns: string[];
  more: boolean;
  refreshing: boolean;
  loading?: boolean;
  onMore: () => void;
  onSelect: (id: string) => void;
  onRefresh: () => void;
  onRunWorkflow: (key: string) => void;
  onEditWorkflow: (key: string) => void;
  filters: HistoryFilters;
  onFilters: (filters: HistoryFilters) => void;
}) {
  const { data: inventory, error } = useResource<{
    workflows: WorkflowEntry[];
  }>(projectPath("/api/workflows", project.id));
  const workflows = inventory?.workflows ?? [];
  const now = useClock(
    runs.some((run) => !run.ended_at && run.started_at !== null),
  );
  const current = workflows.find(
    (workflow) => workflow.key === filters.workflow,
  );
  if (!inventory && !error) return <ViewSkeleton view="runs" />;
  return (
    <Box className="actions-layout">
      <WorkflowSidebar
        workflows={workflows}
        selected={filters.workflow}
        project={project.id}
        onSelect={(workflow) => onFilters({ ...filters, workflow })}
        onCreate={() => onEditWorkflow("")}
      />
      <Stack spacing={2} className="actions-main">
        <Stack direction="row" spacing={2} className="history-heading">
          <Typography component="h1" variant="h5" sx={{ flex: 1 }}>
            {current?.name ?? "All workflows"}
          </Typography>
          <Button
            disabled={refreshing}
            onClick={onRefresh}
            startIcon={<ActionIcon name="refresh" />}
          >
            Refresh
          </Button>
          {current && (
            <Button onClick={() => onEditWorkflow(current.key)}>
              Edit workflow
            </Button>
          )}
        </Stack>
        {error && <Alert severity="error">{error}</Alert>}
        <Paper
          variant="outlined"
          className="run-history"
          aria-label="Run history"
        >
          <Stack direction="row" spacing={1} className="history-filters">
            <TextField
              size="small"
              label="Filter workflow runs"
              value={filters.query}
              onChange={(event) =>
                onFilters({ ...filters, query: event.target.value })
              }
            />
            <FormControl size="small" sx={{ minWidth: 170 }}>
              <InputLabel id="run-status-filter" shrink>
                Status
              </InputLabel>
              <Select
                displayEmpty
                labelId="run-status-filter"
                label="Status"
                value={filters.status}
                onChange={(event) =>
                  onFilters({ ...filters, status: event.target.value })
                }
              >
                <MenuItem value="">All statuses</MenuItem>
                {[
                  "pending",
                  "running",
                  "paused_wait",
                  "succeeded",
                  "failed",
                  "canceled",
                ].map((status) => (
                  <MenuItem key={status} value={status}>
                    {statusLabel(status)}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <TextField
              size="small"
              label="Branch"
              value={filters.branch}
              onChange={(event) =>
                onFilters({ ...filters, branch: event.target.value })
              }
            />
          </Stack>
          {current && (
            <Stack direction="row" className="run-workflow-banner">
              <Typography variant="body2" sx={{ flex: 1 }}>
                {current.key}
              </Typography>
              {!current.disabled && (
                <Button
                  variant="outlined"
                  endIcon={<ActionIcon name="down" />}
                  onClick={() => onRunWorkflow(current.key)}
                >
                  Run workflow
                </Button>
              )}
            </Stack>
          )}
          <List disablePadding>
            {runs.map((run) => (
              <ListItem key={run.id} disablePadding>
                <ListItemButton
                  component="a"
                  href={viewHref("runs", project.id, { run: run.id })}
                  onClick={(event) => {
                    if (
                      event.button === 0 &&
                      !event.metaKey &&
                      !event.ctrlKey &&
                      !event.shiftKey &&
                      !event.altKey
                    ) {
                      event.preventDefault();
                      onSelect(run.id);
                    }
                  }}
                  className="run-history-row"
                >
                  <StatusIcon status={run.status} size={22} />
                  <Box className="history-run-title">
                    <Typography
                      component="p"
                      variant="subtitle1"
                      className="run-title"
                      title={run.title}
                    >
                      {run.title ||
                        stageLabel(
                          run.workflow_key.replace(/\.(yml|yaml)$/, ""),
                        )}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      {stageLabel(
                        run.workflow_key.replace(/\.(yml|yaml)$/, ""),
                      )}{" "}
                      #{run.number} · Started by{" "}
                      {run.launcher === "local" ? "you" : run.launcher} ·{" "}
                      <code>{run.source_commit.slice(0, 7)}</code>
                      {waitingRuns.includes(run.id) ? " · Waiting for you" : ""}
                    </Typography>
                  </Box>
                  {run.source_branch && (
                    <Chip
                      size="small"
                      variant="outlined"
                      label={run.source_branch}
                      icon={<ActionIcon name="branch" />}
                    />
                  )}
                  <Box className="history-run-time">
                    <Typography
                      variant="body2"
                      title={new Date(
                        run.created_at ?? run.started_at ?? "",
                      ).toLocaleString()}
                    >
                      {relativeTime(run.created_at ?? run.started_at, now)}
                    </Typography>
                    <Typography variant="body2" color="text.secondary">
                      <ActionIcon name="clock" size={14} />{" "}
                      {jobDuration(
                        run.started_at,
                        run.ended_at,
                        now,
                        run.status,
                      )}
                    </Typography>
                  </Box>
                </ListItemButton>
              </ListItem>
            ))}
          </List>
          {!runs.length && loading && (
            <ViewSkeleton view="runs" header={false} />
          )}
          {!runs.length && !loading && (
            <Typography color="text.secondary" sx={{ p: 4 }}>
              {filters.status || filters.query || filters.branch
                ? "No runs match these filters."
                : "No runs yet. Choose a workflow to start a run."}
            </Typography>
          )}
          {more && (
            <Button fullWidth onClick={onMore}>
              Load older runs
            </Button>
          )}
        </Paper>
      </Stack>
    </Box>
  );
}
