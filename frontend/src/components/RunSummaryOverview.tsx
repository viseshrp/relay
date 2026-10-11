import { Box, Button, Typography } from "@mui/material";

import { visibleArtifacts } from "../artifacts";

import { ActionIcon } from "./ActionIcon";

import { jobDuration } from "../job";

import { runStatusLabel } from "./RunWorkspaceShared";
import type { RunWorkspaceState } from "./useRunWorkspace";
export function RunSummaryOverview({ state }: { state: RunWorkspaceState }) {
  const { detail, now, artifacts } = state;
  if (!detail) return null;
  return (
    <Box className="run-summary-metadata">
      <Box>
        <Typography variant="body2" color="text.secondary">
          Started manually{" "}
          {detail.started_at
            ? new Date(detail.started_at).toLocaleString()
            : "just now"}
        </Typography>
        <Typography variant="subtitle1">
          {detail.launcher === "local" ? "You" : detail.launcher}{" "}
          <ActionIcon name="commit" size={16} />{" "}
          <code>{detail.source_commit.slice(0, 7)}</code>{" "}
          {detail.source_branch && (
            <Box component="span" className="branch-label">
              {detail.source_branch}
            </Box>
          )}
        </Typography>
      </Box>
      <Box>
        <Typography variant="body2" color="text.secondary">
          Status
        </Typography>
        <Typography variant="subtitle1">{runStatusLabel(detail)}</Typography>
      </Box>
      <Box>
        <Typography variant="body2" color="text.secondary">
          Total elapsed
        </Typography>
        <Typography variant="subtitle1">
          {jobDuration(detail.started_at, detail.ended_at, now, detail.status)}
        </Typography>
        {Boolean(
          detail.dispatch_paused_seconds || detail.dispatch_paused_at,
        ) && (
          <Typography variant="caption">
            Paused:{" "}
            {jobDuration(
              new Date(0).toISOString(),
              new Date(
                ((detail.dispatch_paused_seconds ?? 0) +
                  (detail.dispatch_paused_at
                    ? Math.max(
                        0,
                        ((detail.ended_at ? Date.parse(detail.ended_at) : now) -
                          Date.parse(detail.dispatch_paused_at)) /
                          1000,
                      )
                    : 0)) *
                  1000,
              ).toISOString(),
            )}
          </Typography>
        )}
      </Box>
      <Box>
        <Typography variant="body2" color="text.secondary">
          Artifacts
        </Typography>
        <Button size="small" href="#run-artifacts">
          {visibleArtifacts(artifacts).length || "None"}
        </Button>
      </Box>
    </Box>
  );
}
