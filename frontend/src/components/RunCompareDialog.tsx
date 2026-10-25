import {
  Alert,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";

import { jobDuration } from "../job";
import { projectPath, stageLabel, statusLabel } from "../navigation";
import type {
  ComparedStepSide,
  ComparedValue,
  JsonValue,
  RunComparison,
} from "../types";
import { attemptUsageLabel, runUsageLabel } from "../usage";
import { useResource } from "../useResource";
import { StatusIcon } from "./ActionIcon";

function shown(value: JsonValue | null | undefined): string {
  if (value === null || value === undefined) return "—";
  return typeof value === "string" ? value : JSON.stringify(value);
}

function StepCell({ side }: { side: ComparedStepSide | null }) {
  if (!side) return <Typography color="text.secondary">Not in run</Typography>;
  const attempt = side.latest_attempt;
  return (
    <Stack spacing={0.5}>
      <Typography>
        <StatusIcon status={side.status} size={16} /> {statusLabel(side.status)}
        {side.attempt_count > 1 ? ` · ${side.attempt_count} attempts` : ""}
      </Typography>
      {attempt?.agent_id && (
        <Typography variant="body2">
          {stageLabel(attempt.agent_id)} · {attempt.model_value}
        </Typography>
      )}
      {attempt?.error_code && (
        <Typography variant="body2" color="error">
          {attempt.error_code}
        </Typography>
      )}
      {attempt?.started_at && (
        <Typography variant="body2" color="text.secondary">
          {jobDuration(
            attempt.started_at,
            attempt.ended_at,
            Date.now(),
            attempt.status,
          )}
          {attemptUsageLabel(attempt.usage)
            ? ` · ${attemptUsageLabel(attempt.usage)}`
            : ""}
        </Typography>
      )}
    </Stack>
  );
}

function Values({
  label,
  rows,
  onlyChanged = false,
}: {
  label: string;
  rows: ComparedValue[];
  onlyChanged?: boolean;
}) {
  const visible = onlyChanged ? rows.filter((row) => !row.same) : rows;
  const unchanged = rows.length - visible.length;
  return (
    <Stack spacing={1} component="section" aria-label={label}>
      <Typography variant="h6" component="h3">
        {label}
      </Typography>
      {visible.length ? (
        <Table size="small" aria-label={label}>
          <TableHead>
            <TableRow>
              <TableCell>Name</TableCell>
              <TableCell>First run</TableCell>
              <TableCell>Second run</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {visible.map((row) => (
              <TableRow key={row.name}>
                <TableCell>
                  {row.name}{" "}
                  {!row.same && (
                    <Chip size="small" color="warning" label="Changed" />
                  )}
                </TableCell>
                <TableCell sx={{ overflowWrap: "anywhere" }}>
                  {shown(row.left)}
                </TableCell>
                <TableCell sx={{ overflowWrap: "anywhere" }}>
                  {shown(row.right)}
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      ) : (
        <Typography color="text.secondary">
          {rows.length ? "No differences." : "None."}
        </Typography>
      )}
      {onlyChanged && unchanged > 0 && visible.length > 0 && (
        <Typography variant="body2" color="text.secondary">
          {unchanged} unchanged {unchanged === 1 ? "entry" : "entries"} hidden.
        </Typography>
      )}
    </Stack>
  );
}

/** Two runs side by side: what changed going in, and how each job ended. */
export function RunCompareDialog({
  project,
  left,
  right,
  onClose,
}: {
  project: string;
  left: string;
  right: string;
  onClose: () => void;
}) {
  const { data, error } = useResource<RunComparison>(
    projectPath(
      `/api/runs/compare?left=${encodeURIComponent(left)}&right=${encodeURIComponent(right)}`,
      project,
    ),
  );
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="lg">
      <DialogTitle>Compare runs</DialogTitle>
      <DialogContent>
        {error && <Alert severity="error">{error}</Alert>}
        {!data && !error && <Typography>Loading the comparison…</Typography>}
        {data && (
          <Stack spacing={3}>
            <Table size="small" aria-label="Compared runs">
              <TableBody>
                <TableRow>
                  <TableCell />
                  {[data.left, data.right].map((run) => (
                    <TableCell key={run.id}>
                      <Typography variant="subtitle1">
                        <StatusIcon status={run.status} size={18} />{" "}
                        {run.workflow_name} #{run.number}
                      </Typography>
                      <Typography variant="body2" color="text.secondary">
                        {statusLabel(run.status)} ·{" "}
                        <code>{run.source_commit.slice(0, 7)}</code>
                        {runUsageLabel(run.usage)
                          ? ` · ${runUsageLabel(run.usage)}`
                          : ""}
                      </Typography>
                    </TableCell>
                  ))}
                </TableRow>
              </TableBody>
            </Table>
            <Values label="Inputs" rows={data.inputs} />
            <Values
              label="Captured workflow and prompt files"
              rows={data.hashes}
              onlyChanged
            />
            <Stack spacing={1} component="section" aria-label="Jobs and steps">
              <Typography variant="h6" component="h3">
                Jobs and steps
              </Typography>
              <Table size="small" aria-label="Jobs and steps">
                <TableHead>
                  <TableRow>
                    <TableCell>Step</TableCell>
                    <TableCell>First run</TableCell>
                    <TableCell>Second run</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {data.steps.map((row) => (
                    <TableRow key={row.scope_path}>
                      <TableCell>
                        {row.left?.display_name ??
                          row.right?.display_name ??
                          row.scope_path}
                        <Typography variant="body2" color="text.secondary">
                          {row.scope_path}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <StepCell side={row.left} />
                      </TableCell>
                      <TableCell>
                        <StepCell side={row.right} />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
              {data.truncated && (
                <Alert severity="info">
                  Some steps are not shown because the comparison reached its
                  size limit. Open each run for the full list.
                </Alert>
              )}
            </Stack>
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
