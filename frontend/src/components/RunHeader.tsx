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
        <Button
          size="small"
          aria-label="Refresh"
          disabled={refreshing}
          onClick={() => void refreshRuns()}
        >
          <ActionIcon name="refresh" />
        </Button>
      </Stack>
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
