import { Alert, Button, Stack, Typography } from "@mui/material";

import { stageLabel } from "../navigation";
import type { RunProblem } from "../types";
import { failureReason } from "../failure";

export function RunProblemNotice({
  problem,
  displayScope,
  onShowStep,
  onCancelRetry,
}: {
  problem: RunProblem;
  displayScope?: string;
  onShowStep: (scope: string) => void;
  onCancelRetry: () => void;
}) {
  const scheduled = problem.retry?.state === "scheduled";
  return (
    <Alert severity={scheduled ? "warning" : "error"} sx={{ mt: 2 }}>
      <Stack spacing={1}>
        <Typography variant="subtitle1" component="h2">
          {stageLabel(displayScope ?? problem.scope_path)} stopped
        </Typography>
        <Typography>{failureReason(problem)}</Typography>
        {problem.provider_message && (
          <>
            <Typography variant="subtitle2">
              {problem.agent_id
                ? `${stageLabel(problem.agent_id)} message`
                : "Provider message"}
            </Typography>
            <Typography
              sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
            >
              {problem.provider_message}
            </Typography>
            {problem.provider_message_truncated && (
              <Typography variant="body2">
                Showing part of the provider message. The full message is in
                Activity.
              </Typography>
            )}
          </>
        )}
        <Typography variant="body2">
          Completed steps are saved.{" "}
          {scheduled && problem.retry?.reset_at
            ? `Relay will retry this step after ${new Date(problem.retry.reset_at).toLocaleString()}, using the same model and settings. Keep Relay running; a restart keeps this schedule.`
            : problem.retry?.state === "blocked"
              ? (problem.retry.error_message ??
                "The provider did not supply a confirmed future reset. Automatic retry is stopped; retry manually when the limit is resolved.")
              : problem.retry?.state === "canceled"
                ? "Automatic retry is canceled. You can retry this step manually."
                : problem.error_code === "loop_exhausted"
                  ? "The iteration limit stays spent. Change the workflow for a new run if more iterations are needed."
                  : "Retry this step when the cause is resolved."}
        </Typography>
        <Button
          variant="outlined"
          sx={{ alignSelf: "flex-start" }}
          onClick={() => onShowStep(problem.scope_path)}
        >
          Show stopped step
        </Button>
        {scheduled && (
          <Button
            variant="outlined"
            sx={{ alignSelf: "flex-start" }}
            onClick={onCancelRetry}
          >
            Cancel automatic retry
          </Button>
        )}
      </Stack>
    </Alert>
  );
}
