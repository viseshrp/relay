import { Alert, Box, Stack, Typography } from "@mui/material";
import { JobLog } from "./JobLog";
import type { JobWorkspaceState } from "./useJobWorkspace";
import { failureReason } from "../failure";

export function StepLogEmbedded({ state }: { state: JobWorkspaceState }) {
  const {
    job,
    failed,
    attempt,
    activityType,
    error,
    outputLabel,
    runId,
    scope,
    events,
    loadingLogs,
    logsComplete,
    setLogRevision,
  } = state;

  return (
    <Stack
      spacing={1}
      component="section"
      aria-label="Step log"
      className="job-workspace step-workspace-embedded"
    >
      {error && <Alert severity="error">{error}</Alert>}
      {failed && (
        <Alert severity="error">
          <Typography>{failureReason(attempt, "Step")}</Typography>
          {attempt?.provider_message && (
            <Typography sx={{ whiteSpace: "pre-wrap" }}>
              {attempt.provider_message}
            </Typography>
          )}
          {state.lastError && (
            <Box
              component="pre"
              sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", m: 0 }}
            >
              {state.lastError}
            </Box>
          )}
        </Alert>
      )}
      {attempt ? (
        <JobLog
          key={`${runId}:${scope}:${attempt?.number}`}
          events={events}
          label={outputLabel}
          workingFolder={job.working_folder}
          live={attempt?.status === "running" || attempt?.status === "waiting"}
          command={activityType === "command"}
          loading={loadingLogs}
          hasMore={!logsComplete}
          onMore={async () => setLogRevision((value) => value + 1)}
          onRefresh={() => setLogRevision((value) => value + 1)}
          scope={scope}
          attempt={attempt.number}
        />
      ) : (
        <Typography sx={{ p: 1 }}>
          {["canceled", "skipped"].includes(job.status)
            ? "This step did not run."
            : "No attempt has started yet."}
        </Typography>
      )}
    </Stack>
  );
}
