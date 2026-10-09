import { RunSettingsDetails } from "./RunSettingsDetails";
import { RunDiagnostics } from "./RunDiagnostics";
import { RunRepairDetails } from "./RunRepairDetails";
import { RunSummaryOverview } from "./RunSummaryOverview";

import { Alert, Box, Button, Paper, Stack, Typography } from "@mui/material";

import { stageLabel } from "../navigation";

import { FlowCanvas } from "./FlowCanvas";
import { ReviewEvidence } from "./RunReview";
import { WaitingRequests } from "./WaitingRequests";
import { attentionChanged } from "../attention";
import { RunProblemNotice } from "./RunProblemNotice";

import { JobWorkspace } from "./JobWorkspace";

import { ActivityFeed } from "./ActivityFeed";
import { RunArtifacts } from "./RunArtifacts";

import { StatusIcon } from "./ActionIcon";

import { ActionsRunProducts } from "./ActionsRunProducts";
import { TERMINAL_RUNS } from "./RunWorkspaceShared";
import type { RunWorkspaceState } from "./useRunWorkspace";
export function RunMain({ state }: { state: RunWorkspaceState }) {
  const {
    jobContent,
    detail,
    events,
    pendingInteractions,
    artifacts,
    selectedInteraction,
    interactionCursor,
    loadMoreInteractions,
    refreshDetail,
    selectedJob,
    refreshing,
    rerunNode,
    setRetrySettings,
    dispatchPaused,
    summaryMessage,
    project,
    linkedRequest,
    stepProgress,
    visibleStages,
    graph,
    repairOwners,
    focusStage,
    setGraphJobs,
    showStep,
    cancelRun,
    artifactCursor,
    loadMoreArtifacts,
    repairGroups,
    eventCursor,
    loadEvents,
  } = state;
  if (!detail) return null;
  return (
    <Stack
      id="run-summary"
      tabIndex={-1}
      ref={jobContent}
      spacing={2}
      sx={{ minWidth: 0, scrollMarginTop: 80 }}
    >
      {detail &&
        detail.nodes.some((node) => node.node_type === "actions_job") && (
          <ActionsRunProducts
            runId={detail.id}
            projectId={detail.project_id}
            events={events}
            nodes={detail.nodes}
          />
        )}
      {detail && (
        <WaitingRequests
          key={detail.id}
          requests={pendingInteractions}
          runId={detail.id}
          artifacts={artifacts}
          selected={selectedInteraction}
          hasMore={interactionCursor !== null}
          onMore={() => void loadMoreInteractions()}
          onAnswered={async () => {
            await refreshDetail();
            attentionChanged();
          }}
        />
      )}
      {detail === null ? (
        <Paper variant="outlined" className="empty-panel">
          <Typography color="text.secondary">
            Select a run to inspect it.
          </Typography>
        </Paper>
      ) : selectedJob ? (
        <JobWorkspace
          key={`${detail.id}:${selectedJob}`}
          nodes={detail.nodes}
          runId={detail.id}
          scope={selectedJob}
          liveEvents={events}
          canRetry={detail.status === "failed"}
          refreshing={refreshing}
          onRetry={rerunNode}
          onRetrySettings={setRetrySettings}
        />
      ) : (
        <>
          <Paper variant="outlined" className="section-card">
            <RunSummaryOverview state={state} />
            {!dispatchPaused && (
              <Typography variant="body2" color="text.secondary" sx={{ mt: 2 }}>
                {summaryMessage}
              </Typography>
            )}
            {detail.status === "completing" && (
              <Alert severity="info" sx={{ mt: 2 }}>
                Every job finished. Relay is merging into {detail.source_branch}{" "}
                and deleting the run working copies.
              </Alert>
            )}
            {detail.merged_commit && (
              <Alert severity="success" sx={{ mt: 2 }}>
                Merged into {detail.source_branch} at{" "}
                <code>{detail.merged_commit.slice(0, 7)}</code>.{" "}
                {detail.worktree_state === "removed"
                  ? "Run working copies deleted."
                  : "The run working copy still needs cleanup."}
              </Alert>
            )}
            <Button
              size="small"
              component="a"
              href={`?view=runs&project=${project.id}&run=${detail.id}`}
            >
              Link to run
            </Button>
            {detail.status === "interrupted" && (
              <Alert severity="info" sx={{ mt: 2 }}>
                Restarting <code>relay up</code> resumes this run from durable
                state as a fresh attempt.
              </Alert>
            )}
          </Paper>

          {selectedInteraction &&
            linkedRequest &&
            linkedRequest.status !== "pending" && (
              <Alert severity="info">
                The linked request has already been {linkedRequest.status}. Any
                current requests appear above.
              </Alert>
            )}

          <Paper
            ref={stepProgress}
            variant="outlined"
            className="canvas-panel run-canvas"
            role="region"
            aria-label="Step progress"
            tabIndex={-1}
          >
            <Box className="graph-heading">
              <Typography variant="h6">{detail.workflow_key}</Typography>
              <Typography variant="body2" color="text.secondary">
                Started manually · {visibleStages.length}{" "}
                {visibleStages.length === 1 ? "job" : "jobs"}
              </Typography>
            </Box>
            <Box className="run-graph-viewport">
              <FlowCanvas
                key={detail.id}
                runMode
                nodes={graph.nodes}
                edges={graph.edges}
                selectedId={repairOwners.get(focusStage ?? "") ?? focusStage}
                onSelect={(id) => {
                  const members = graph.nodes.find((node) => node.id === id)
                    ?.data.members;
                  if (
                    Array.isArray(members) &&
                    members.every(
                      (value): value is string => typeof value === "string",
                    )
                  )
                    setGraphJobs(members);
                  else if (detail.nodes.some((node) => node.scope_path === id))
                    showStep(id);
                }}
              />
            </Box>
          </Paper>
          {(detail.nodes.some((node) => node.status === "failed") ||
            detail.problem ||
            detail.failure_summary) && (
            <Paper
              variant="outlined"
              className="section-card"
              aria-label="Annotations"
            >
              <Typography variant="h6">Annotations</Typography>
              {detail.problem &&
              ["failed", "canceling"].includes(detail.status) ? (
                <RunProblemNotice
                  problem={detail.problem}
                  displayScope={repairOwners.get(detail.problem.scope_path)}
                  onShowStep={showStep}
                  onCancelRetry={() => void cancelRun()}
                />
              ) : (
                detail.failure_summary && (
                  <Alert severity="error" sx={{ mt: 2 }}>
                    {detail.failure_summary}
                  </Alert>
                )
              )}
              {detail.nodes
                .filter((node) => node.status === "failed")
                .map((node) => (
                  <Stack
                    key={node.id}
                    direction="row"
                    spacing={2}
                    sx={{ mt: 1, alignItems: "center" }}
                  >
                    <StatusIcon status="failed" />
                    <Typography sx={{ flex: 1 }}>
                      {stageLabel(node.scope_path)}
                    </Typography>
                    <Button onClick={() => showStep(node.scope_path)}>
                      Open job log
                    </Button>
                  </Stack>
                ))}
            </Paper>
          )}
          <RunSettingsDetails state={state} />
          <RunArtifacts
            runId={detail.id}
            artifacts={artifacts}
            more={artifactCursor !== null}
            onMore={() => void loadMoreArtifacts()}
          />
          {repairGroups.length > 0 && <RunRepairDetails state={state} />}

          <Paper variant="outlined" className="section-card">
            <Typography variant="h6" sx={{ mb: 1.5 }}>
              Activity
            </Typography>
            <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
              Messages and tool results from this run, in order.
            </Typography>
            <ActivityFeed
              key={detail.id}
              events={events}
              nodes={detail.nodes}
              workingFolder={detail.working_folder}
              live={!TERMINAL_RUNS.has(detail.status)}
              hasMore={eventCursor !== null}
              onMore={async () => {
                if (eventCursor !== null) await loadEvents(eventCursor);
              }}
            />
          </Paper>

          {pendingInteractions.length === 0 && (
            <Paper variant="outlined" className="section-card">
              <ReviewEvidence runId={detail.id} artifacts={artifacts} />
            </Paper>
          )}

          <RunDiagnostics state={state} />
        </>
      )}
    </Stack>
  );
}
