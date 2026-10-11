import {
  Divider,
  ListItemButton,
  ListItemText,
  Paper,
  Typography,
} from "@mui/material";

import { JobList } from "./JobList";

import { ActionIcon } from "./ActionIcon";

import type { RunWorkspaceState } from "./useRunWorkspace";
export function RunJobSidebar({ state }: { state: RunWorkspaceState }) {
  const {
    detail,
    selectedJob,
    repairOwners,
    nodeCursor,
    showStep,
    onSelectJob,
    loadMoreNodes,
    pendingChoices,
    dispatchPaused,
    setPendingSettings,
    setShowArtifacts,
    setWorkflowFileOpen,
    onSelectRun,
  } = state;
  if (!detail) return null;
  return (
    <Paper variant="outlined" className="history-panel actions-sidebar">
      {detail && (
        <>
          <a
            className="skip-link skip-summary"
            href="#run-summary"
            onClick={() => document.getElementById("run-summary")?.focus()}
          >
            Skip to summary
          </a>
          <JobList
            nodes={detail.nodes}
            selected={selectedJob}
            repairOwners={repairOwners}
            hasMore={nodeCursor !== null}
            onSelect={(scope) => (scope ? showStep(scope) : onSelectJob(null))}
            onMore={() => void loadMoreNodes()}
            pendingChoices={dispatchPaused ? pendingChoices.choices : undefined}
            onCheck={pendingChoices.retry}
            onEdit={(settings, choices) =>
              setPendingSettings({ runId: detail.id, settings, choices })
            }
          />
        </>
      )}
      <Divider sx={{ my: 2 }} />
      <Typography variant="caption" color="text.secondary" sx={{ px: 2 }}>
        Run details
      </Typography>
      <ListItemButton
        onClick={() => {
          onSelectJob(null);
          setShowArtifacts(true);
        }}
      >
        <ActionIcon name="artifact" />
        <ListItemText primary="Artifacts" />
      </ListItemButton>
      {detail && (
        <ListItemButton onClick={() => setWorkflowFileOpen(true)}>
          <ActionIcon name="workflow" />
          <ListItemText primary="Workflow file" />
        </ListItemButton>
      )}
      <ListItemButton onClick={() => onSelectRun(null)}>
        <ActionIcon name="clock" />
        <ListItemText primary="Run history" />
      </ListItemButton>
    </Paper>
  );
}
