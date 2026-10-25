import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  Typography,
} from "@mui/material";

import { stageLabel } from "../navigation";
import { runUsageLabel } from "../usage";
import { useState } from "react";
import { WorkflowNoteForm } from "./WorkflowNoteForm";

import { RunActions } from "./RunActions";

import { ActionIcon, StatusIcon } from "./ActionIcon";

import type { RunWorkspaceState } from "./useRunWorkspace";
export function RunHeader({ state }: { state: RunWorkspaceState }) {
  const {
    onSelectRun,
    detail,
    onRunWorkflow,
    pauseBusy,
    relaunchBusy,
    refreshing,
    configurePause,
    setStopOpen,
    rerunAll,
    setGraphJobs,
    relaunchButton,
    refreshRuns,
    setFullTitle,
    fullTitle,
  } = state;
  const [saveNoteOpen, setSaveNoteOpen] = useState(false);
  if (!detail) return null;
  return (
    <Box component="header" aria-labelledby="run-title" className="run-header">
      <Button
        size="small"
        startIcon={<ActionIcon name="back" />}
        onClick={() => onSelectRun(null)}
      >
        {detail.workflow_name || detail.workflow_key}
      </Button>
      <Stack direction="row" spacing={2} className="run-heading-row">
        <Typography
          component="h1"
          variant="h5"
          id="run-title"
          title={detail.title}
          sx={{ flex: 1 }}
        >
          <StatusIcon status={detail.status} size={26} />{" "}
          <span className="run-title">
            {detail.title ||
              stageLabel(detail.workflow_key.replace(/\.(yaml|yml)$/, ""))}
          </span>
          <Box component="span" className="run-number" color="text.secondary">
            #{detail.number}
          </Box>
        </Typography>
        <Button
          variant="outlined"
          onClick={() => onRunWorkflow(detail.workflow_key)}
        >
          Run workflow
        </Button>
        <RunActions
          run={detail}
          busy={pauseBusy || relaunchBusy || refreshing}
          onPause={() => void configurePause(!detail.dispatch_paused)}
          onCancel={() => setStopOpen(true)}
          onRerunAll={() => void rerunAll()}
          onRerunFailed={() =>
            setGraphJobs(
              detail.nodes
                .filter((node) => node.status === "failed")
                .map((node) => node.scope_path),
            )
          }
          rerunAllRef={relaunchButton}
        />
        {["succeeded", "failed", "canceled"].includes(detail.status) && (
          <Button onClick={() => setSaveNoteOpen(true)}>Save as note</Button>
        )}
        <Button
          size="small"
          aria-label="Refresh"
          disabled={refreshing}
          onClick={() => void refreshRuns()}
        >
          <ActionIcon name="refresh" />
        </Button>
      </Stack>
      {saveNoteOpen && (
        <Dialog open onClose={() => setSaveNoteOpen(false)} fullWidth>
          <DialogTitle>Save a lesson from this run</DialogTitle>
          <DialogContent>
            <Stack spacing={2} sx={{ pt: 1 }}>
              <Typography variant="body2">
                The note links to run #{detail.number}. It applies only to runs
                you start later and choose it for.
              </Typography>
              <WorkflowNoteForm
                workflowKey={detail.workflow_key}
                project={detail.project.id}
                evidenceRunId={detail.id}
                initialEvidence={`Run #${detail.number} (${stageLabel(detail.status)}): `}
                onSaved={() => setSaveNoteOpen(false)}
                onCancel={() => setSaveNoteOpen(false)}
              />
            </Stack>
          </DialogContent>
        </Dialog>
      )}
      {runUsageLabel(detail.usage) && (
        <Typography variant="body2" color="text.secondary">
          Provider usage: {runUsageLabel(detail.usage)}
        </Typography>
      )}
      {(detail.title?.length ?? 0) > 100 && (
        <Button onClick={() => setFullTitle(true)}>Show full title</Button>
      )}
      <Dialog open={fullTitle} onClose={() => setFullTitle(false)} fullWidth>
        <DialogTitle>Run title</DialogTitle>
        <DialogContent tabIndex={0}>
          <Typography sx={{ overflowWrap: "anywhere" }}>
            {detail.title}
          </Typography>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setFullTitle(false)}>Close</Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
