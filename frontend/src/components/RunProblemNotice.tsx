import { Alert, Button, Stack, Typography } from "@mui/material";

import { stageLabel } from "../navigation";
import type { RunProblem } from "../types";

function failureReason(problem: RunProblem): string {
  if (problem.message) return problem.message;
  if (problem.exit_code !== null && problem.exit_code !== 0) {
    return `The tool exited with code ${problem.exit_code}. Open the step's activity for its output.`;
  }
  const reasons: Record<string, string> = {
    agent_protocol_error: "The agent stopped before completing its request.",
    agent_auth_error: "The agent needs a working sign-in before it can continue.",
    agent_launch_error: "Relay could not start the selected agent.",
    model_unavailable_error: "The selected model is unavailable from the configured tools.",
    model_selection_rejected_error: "The agent rejected the selected model.",
    agent_configuration_error: "The agent rejected the requested configuration.",
    output_validation_error: "The step did not produce its required output.",
    node_timeout: "The step reached its time limit.",
    worker_lost: "The worker stopped before finishing this step.",
    soft_denied: "The tool did not have permission to complete its work.",
    git_error: "A Git operation could not complete.",
    worktree_error: "Relay could not prepare or clean up the working folder.",
  };
  return reasons[problem.error_code ?? ""] ?? reasons[problem.stop_reason ?? ""]
    ?? "The step could not finish. Open its activity to inspect the cause.";
}

export function RunProblemNotice({ problem, onShowStep }: {
  problem: RunProblem;
  onShowStep: (scope: string) => void;
}) {
  return <Alert severity="error" sx={{ mt: 2 }}>
    <Stack spacing={1}>
      <Typography variant="subtitle1" component="h2">
        {stageLabel(problem.scope_path)} stopped
      </Typography>
      <Typography>{failureReason(problem)}</Typography>
      {problem.provider_message && <>
        <Typography variant="subtitle2">
          {problem.agent_id ? `${stageLabel(problem.agent_id)} message` : "Provider message"}
        </Typography>
        <Typography sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
          {problem.provider_message}
        </Typography>
        {problem.provider_message_truncated && <Typography variant="body2">
          Showing part of the provider message. The full message is in Activity.
        </Typography>}
      </>}
      <Typography variant="body2">
        Completed steps are saved. Retry this step when the cause is resolved.
        {problem.provider_message && " For a provider limit, wait until its reported reset."}
      </Typography>
      <Button variant="outlined" sx={{ alignSelf: "flex-start" }} onClick={() => onShowStep(problem.scope_path)}>
        Show stopped step
      </Button>
    </Stack>
  </Alert>;
}
