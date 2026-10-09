import {
  Alert,
  Box,
  Button,
  FormControl,
  InputLabel,
  MenuItem,
  Paper,
  Select,
  Stack,
  Typography,
} from "@mui/material";

import { errorMessage } from "../api";
import { jobDuration } from "../job";
import { stageLabel, statusLabel } from "../navigation";

import { StatusIcon } from "./ActionIcon";

import type { JobWorkspaceState } from "./useJobWorkspace";
export function JobHeader({ state }: { state: JobWorkspaceState }) {
  const {
    heading,
    embedded,
    job,
    label,
    failed,
    attempt,
    lastError,
    activityType,
    now,
    scope,
    attempts,
    setAttemptNumber,
    canRetry,
    busy,
    refreshing,
    loadingJob,
    setBusy,
    onRetry,
    setError,
    openRetrySettings,
    attemptCursor,
    moreAttempts,
  } = state;
  return (
    <Paper variant="outlined" className="section-card job-heading">
      <Typography
        ref={heading}
        tabIndex={-1}
        component={embedded ? "h3" : "h2"}
        variant={embedded ? "subtitle1" : "h5"}
        sx={{ scrollMarginTop: 90 }}
      >
        <span aria-hidden="true">
          <StatusIcon status={job.status} size={22} />
        </span>{" "}
        {label}
      </Typography>
      {failed && (
        <Alert severity="error" sx={{ mt: 1 }}>
          <Typography>
            {attempt?.error_message ??
              `Job failed${attempt?.exit_code !== null ? ` with exit code ${attempt?.exit_code}` : ""}.`}
          </Typography>
          {attempt?.provider_message && (
            <Typography sx={{ whiteSpace: "pre-wrap" }}>
              {attempt.provider_message}
            </Typography>
          )}
          {lastError && (
            <Box
              component="pre"
              sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", m: 0 }}
            >
              {lastError}
            </Box>
          )}
        </Alert>
      )}
      <Typography sx={{ mt: 1 }}>
        {attempt?.agent_id
          ? `Runs on ${stageLabel(attempt.agent_id)} · ${attempt.model_value}`
          : activityType === "human_wait"
            ? "Human review"
            : stageLabel(activityType)}{" "}
        ·{" "}
        {jobDuration(
          attempt?.started_at,
          attempt?.ended_at,
          now,
          attempt?.status ?? job.status,
        )}
      </Typography>
      <Stack
        direction="row"
        spacing={1}
        useFlexGap
        sx={{ mt: 2, flexWrap: "wrap", alignItems: "center" }}
      >
        <FormControl size="small" sx={{ minWidth: 190 }}>
          <InputLabel id={`job-attempt-${scope}`} shrink>
            Attempt
          </InputLabel>
          <Select
            displayEmpty
            renderValue={!attempt ? () => "Not started" : undefined}
            labelId={`job-attempt-${scope}`}
            label="Attempt"
            disabled={!attempts.length}
            value={attempt?.number ?? ""}
            onChange={(event) => setAttemptNumber(Number(event.target.value))}
          >
            {attempts.map((row) => (
              <MenuItem key={row.number} value={row.number}>
                Attempt {row.number} ·{" "}
                {row.stop_reason
                  ? stageLabel(row.stop_reason)
                  : statusLabel(row.status)}
              </MenuItem>
            ))}
          </Select>
        </FormControl>
        {canRetry && job.status === "failed" && (
          <>
            <Button
              variant="outlined"
              disabled={busy || refreshing || loadingJob}
              onClick={() => {
                setBusy(true);
                void onRetry(scope)
                  .catch((caught: unknown) => setError(errorMessage(caught)))
                  .finally(() => setBusy(false));
              }}
            >
              Re-run job
            </Button>
            {job.retry_settings && (
              <Button
                disabled={busy || refreshing || loadingJob}
                onClick={() => void openRetrySettings()}
              >
                Re-run with settings
              </Button>
            )}
          </>
        )}
        {attemptCursor !== null && (
          <Button onClick={() => void moreAttempts()}>
            Load more attempts
          </Button>
        )}
      </Stack>
    </Paper>
  );
}
