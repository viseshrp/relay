import { RunHeader } from "./RunHeader";
import { RunJobSidebar } from "./RunJobSidebar";
import { RunMain } from "./RunMain";

import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  List,
  ListItemButton,
  ListItemText,
  Stack,
} from "@mui/material";

import { stageLabel } from "../navigation";

import { RetrySettings } from "./RetrySettings";

import { LaunchPanel } from "./LaunchPanel";

import { RunWorkflowFile } from "./RunWorkflowFile";
import { RunHistory } from "./RunHistory";

import { StatusIcon } from "./ActionIcon";

import type { RunWorkspaceState } from "./useRunWorkspace";
export function RunWorkspaceView({ state }: { state: RunWorkspaceState }) {
  const {
    detail,
    onSelectRun,
    onRunWorkflow,
    refreshing,
    setStopOpen,
    setGraphJobs,
    relaunchButton,
    refreshRuns,
    dispatchPaused,
    pendingSettings,
    setPendingSettings,
    savePendingSettings,
    runAgain,
    project,
    setRunAgain,
    retrySettings,
    setRetrySettings,
    rerunNode,
    error,
    setError,
    workflowFileOpen,
    setWorkflowFileOpen,
    onEditWorkflow,
    selectedRun,
    runs,
    waitingRuns,
    runCursor,
    loadHistory,
    filters,
    setLocalFilters,
    onSelectWorkflow,
    showStep,
    cancelRun,
    graphJobs,
    stopOpen,
  } = state;
  return (
    <Stack spacing={2}>
      {detail && <RunHeader state={state} />}
      {dispatchPaused && (
        <Alert severity="info">
          Paused. Running jobs will finish; nothing new will start until you
          resume.
        </Alert>
      )}
      {pendingSettings &&
        detail?.id === pendingSettings.runId &&
        dispatchPaused && (
          <RetrySettings
            key={`${pendingSettings.runId}:${pendingSettings.settings.scope_path}:pending`}
            purpose="pending"
            problem={pendingSettings.settings}
            initialChoices={pendingSettings.choices}
            projectId={detail.project_id}
            onClose={() => setPendingSettings(null)}
            onRetry={savePendingSettings}
          />
        )}
      {runAgain && (
        <LaunchPanel
          open={runAgain.open}
          workflowKey={runAgain.source.workflow_key}
          workflow={runAgain.workflow}
          project={project}
          requestProject={runAgain.source.project_id}
          modelOptions={runAgain.models}
          previousRun={runAgain.source}
          blockedReason={
            Object.keys(runAgain.workflow.nodes).length === 0
              ? "Add a job to this empty workflow before running it."
              : null
          }
          saveError={null}
          onClose={() =>
            setRunAgain((current) =>
              current ? { ...current, open: false } : null,
            )
          }
          onExited={() => {
            setRunAgain(null);
            relaunchButton.current?.focus();
          }}
          onRunLaunched={(id) => {
            setRunAgain(null);
            onSelectRun(id);
          }}
        />
      )}
      {retrySettings && detail && (
        <RetrySettings
          key={`${detail.id}:${retrySettings.scope_path}`}
          problem={retrySettings}
          projectId={detail.project_id}
          onClose={() => setRetrySettings(null)}
          onRetry={rerunNode}
        />
      )}
      {error && (
        <Alert severity="error" onClose={() => setError(null)}>
          {error}
        </Alert>
      )}
      {workflowFileOpen && detail && (
        <RunWorkflowFile
          key={detail.id}
          runId={detail.id}
          onClose={() => setWorkflowFileOpen(false)}
          onEdit={(key) => {
            setWorkflowFileOpen(false);
            onEditWorkflow(key);
          }}
        />
      )}
      {!selectedRun ? (
        <RunHistory
          project={project}
          runs={runs}
          waitingRuns={waitingRuns}
          more={Boolean(runCursor)}
          refreshing={refreshing}
          onMore={() => void loadHistory(runCursor ?? undefined)}
          onSelect={onSelectRun}
          onRefresh={() => void refreshRuns()}
          onRunWorkflow={onRunWorkflow}
          onEditWorkflow={onEditWorkflow}
          filters={filters}
          onFilters={(next) => {
            setLocalFilters({
              status: next.status,
              branch: next.branch,
              query: next.query,
            });
            if (next.workflow !== filters.workflow)
              onSelectWorkflow(next.workflow || null);
          }}
        />
      ) : (
        <Box className="run-layout">
          <RunJobSidebar state={state} />

          <RunMain state={state} />
        </Box>
      )}
      <Dialog
        open={graphJobs !== null}
        onClose={() => setGraphJobs(null)}
        fullWidth
      >
        <DialogTitle>
          {graphJobs?.every(
            (scope) =>
              detail?.nodes.find((node) => node.scope_path === scope)
                ?.status === "failed",
          )
            ? "Choose a failed job"
            : "Parallel jobs"}
        </DialogTitle>
        <DialogContent>
          <List>
            {graphJobs?.map((scope) => (
              <ListItemButton
                key={scope}
                onClick={() => {
                  setGraphJobs(null);
                  showStep(scope);
                }}
              >
                <StatusIcon
                  status={
                    detail?.nodes.find((node) => node.scope_path === scope)
                      ?.status ?? "pending"
                  }
                />
                <ListItemText primary={stageLabel(scope)} />
              </ListItemButton>
            ))}
          </List>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setGraphJobs(null)}>Close</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={stopOpen} onClose={() => setStopOpen(false)}>
        <DialogTitle>Cancel this run?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Relay stops active tools and skips remaining work. Finished jobs
            keep their results and committed changes. You can still review the
            saved evidence.
          </DialogContentText>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setStopOpen(false)}>Keep working</Button>
          <Button
            color="error"
            onClick={() => {
              setStopOpen(false);
              void cancelRun();
            }}
          >
            Cancel run
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
