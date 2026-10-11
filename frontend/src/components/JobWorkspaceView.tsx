import { JobWorkspace } from "./JobWorkspace";
import { JobHeader } from "./JobHeader";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";

import { jobDuration } from "../job";
import { stageLabel, statusLabel } from "../navigation";

import { JobLog } from "./JobLog";
import { ActionIcon, StatusIcon } from "./ActionIcon";

import { JobChangesView } from "./JobWorkspaceShared";
import type { JobWorkspaceState } from "./useJobWorkspace";
export function JobWorkspaceView({ state }: { state: JobWorkspaceState }) {
  const {
    embedded,
    job,
    failed,
    attempt,
    activityType,
    now,
    scope,
    canRetry,
    refreshing,
    onRetry,
    error,
    panels,
    setPanel,
    outputLabel,
    runId,
    events,
    loadingLogs,
    logsComplete,
    setLogRevision,
    steps,
    nodes,
    liveEvents,
    onRetrySettings,
    changesOpen,
    setChangesOpen,
  } = state;
  return (
    <Stack
      spacing={0}
      component="section"
      aria-label={embedded ? "Step log" : "Job log"}
      className="job-workspace"
    >
      <JobHeader state={state} />
      {error && <Alert severity="error">{error}</Alert>}
      {job.node_type !== "actions_job" && (
        <>
          <Accordion
            expanded={panels.setup ?? false}
            onChange={(_, expanded) => setPanel("setup", expanded)}
          >
            <AccordionSummary expandIcon={<ActionIcon name="chevron" />}>
              Set up
            </AccordionSummary>
            <AccordionDetails>
              <Typography>
                {job.writes
                  ? "This job can write to its isolated working folder."
                  : "This job reads its isolated working folder."}
              </Typography>
              <Typography>Captured job: {scope}</Typography>
              {job.command && (
                <Box component="pre" className="activity-text">
                  {job.command.join("\n")}
                </Box>
              )}
            </AccordionDetails>
          </Accordion>
          <Accordion
            expanded={panels.instructions ?? false}
            onChange={(_, expanded) => setPanel("instructions", expanded)}
          >
            <AccordionSummary expandIcon={<ActionIcon name="chevron" />}>
              Instructions
            </AccordionSummary>
            <AccordionDetails>
              {job.prompt && (
                <Typography sx={{ whiteSpace: "pre-wrap" }}>
                  {job.prompt}
                </Typography>
              )}
              {job.instructions.map((instruction, index) => (
                <Box key={index} sx={{ mb: 2 }}>
                  <Typography variant="subtitle2">
                    {instruction.reference.local ??
                      instruction.reference.global}
                  </Typography>
                  <Box component="pre" className="activity-text">
                    {instruction.text}
                  </Box>
                  {instruction.truncated && (
                    <Alert severity="info">
                      This captured instruction exceeds the preview limit.
                    </Alert>
                  )}
                </Box>
              ))}
              {!job.prompt && !job.instructions.length && (
                <Typography>
                  No prompt files were captured for this job.
                </Typography>
              )}
            </AccordionDetails>
          </Accordion>
          <Accordion
            expanded={
              panels.output ??
              (failed || activityType === "command" || activityType === "agent")
            }
            onChange={(_, expanded) => setPanel("output", expanded)}
          >
            <AccordionSummary
              aria-label={outputLabel}
              expandIcon={<ActionIcon name="chevron" />}
            >
              <span aria-hidden="true">
                <StatusIcon
                  status={
                    attempt?.status === "succeeded" ? "succeeded" : job.status
                  }
                />
              </span>{" "}
              {outputLabel}
              <Typography className="step-duration" variant="caption">
                {jobDuration(
                  attempt?.started_at,
                  attempt?.ended_at,
                  now,
                  attempt?.status ?? job.status,
                )}
              </Typography>
            </AccordionSummary>
            <AccordionDetails>
              {attempt ? (
                <JobLog
                  key={`${runId}:${scope}:${attempt?.number}`}
                  events={events}
                  label={outputLabel}
                  workingFolder={job.working_folder}
                  live={
                    attempt?.status === "running" ||
                    attempt?.status === "waiting"
                  }
                  command={activityType === "command"}
                  loading={loadingLogs}
                  hasMore={!logsComplete}
                  onMore={async () => setLogRevision((value) => value + 1)}
                  onRefresh={() => setLogRevision((value) => value + 1)}
                  scope={scope}
                  attempt={attempt.number}
                />
              ) : (
                <Typography>
                  {["canceled", "skipped"].includes(job.status)
                    ? "This job did not run."
                    : "No attempt has started yet."}
                </Typography>
              )}
            </AccordionDetails>
          </Accordion>
        </>
      )}
      {steps.length > 0 && (
        <Stack component="section" aria-label="Job steps" spacing={1}>
          {steps.map((step, index) => (
            <Accordion
              key={step.id}
              expanded={panels[step.scope_path] ?? false}
              onChange={(_, expanded) => setPanel(step.scope_path, expanded)}
            >
              <AccordionSummary expandIcon={<ActionIcon name="chevron" />}>
                <StatusIcon status={step.status} />{" "}
                <Typography sx={{ ml: 1, flex: 1 }}>
                  {index + 1}.{" "}
                  {step.display_name && step.display_name !== step.node_id
                    ? step.display_name
                    : stageLabel(step.scope_path)}
                </Typography>
                <Typography variant="caption">
                  {jobDuration(
                    step.started_at,
                    step.ended_at,
                    now,
                    step.status,
                  )}
                </Typography>
              </AccordionSummary>
              <AccordionDetails>
                {panels[step.scope_path] && (
                  <JobWorkspace
                    embedded
                    nodes={nodes}
                    runId={runId}
                    scope={step.scope_path}
                    liveEvents={liveEvents}
                    canRetry={canRetry}
                    refreshing={refreshing}
                    onRetry={onRetry}
                    onRetrySettings={onRetrySettings}
                  />
                )}
              </AccordionDetails>
            </Accordion>
          ))}
        </Stack>
      )}
      <Accordion
        expanded={panels.outputs ?? false}
        onChange={(_, expanded) => setPanel("outputs", expanded)}
      >
        <AccordionSummary expandIcon={<ActionIcon name="chevron" />}>
          Outputs
        </AccordionSummary>
        <AccordionDetails>
          {attempt?.number === job.latest_attempt?.number ? (
            Object.keys(job.outputs).length ? (
              <Table size="small" aria-label="Declared outputs">
                <TableHead>
                  <TableRow>
                    <TableCell>Name</TableCell>
                    <TableCell>Value</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {Object.entries(job.outputs).map(([name, value]) => (
                    <TableRow key={name}>
                      <TableCell>{name}</TableCell>
                      <TableCell>
                        {typeof value === "object" && value !== null ? (
                          <Box component="details">
                            <Box component="summary">Details</Box>
                            <Box component="pre" className="activity-text">
                              {JSON.stringify(value, null, 2)}
                            </Box>
                          </Box>
                        ) : (
                          String(value)
                        )}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            ) : (
              <Typography>No declared outputs.</Typography>
            )
          ) : (
            <Typography>
              Declared outputs describe the latest attempt. Select it to see
              them.
            </Typography>
          )}
        </AccordionDetails>
      </Accordion>
      <Accordion
        expanded={changesOpen}
        onChange={(_event, expanded) => setChangesOpen(expanded)}
      >
        <AccordionSummary expandIcon={<ActionIcon name="chevron" />}>
          Changes
        </AccordionSummary>
        <AccordionDetails>
          {changesOpen && attempt ? (
            <JobChangesView runId={runId} scope={scope} attempt={attempt} />
          ) : (
            <Typography>No attempt has started.</Typography>
          )}
        </AccordionDetails>
      </Accordion>
      <Accordion
        expanded={panels.complete ?? false}
        onChange={(_, expanded) => setPanel("complete", expanded)}
      >
        <AccordionSummary expandIcon={<ActionIcon name="chevron" />}>
          Result
        </AccordionSummary>
        <AccordionDetails>
          <Typography>
            {attempt?.stop_reason
              ? stageLabel(attempt.stop_reason)
              : statusLabel(job.status)}
            {attempt?.exit_code !== null && attempt?.exit_code !== undefined
              ? ` · Exit code ${attempt.exit_code}`
              : ""}
          </Typography>
          {attempt?.ended_at && (
            <Typography>
              Finished {new Date(attempt.ended_at).toLocaleString()}
            </Typography>
          )}
        </AccordionDetails>
      </Accordion>
    </Stack>
  );
}
