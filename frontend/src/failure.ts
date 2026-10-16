type FailureDetails = {
  message?: string | null;
  error_message?: string | null;
  exit_code?: number | null;
  error_code?: string | null;
  stop_reason?: string | null;
};

const reasons: Record<string, string> = {
  agent_protocol_error: "The agent stopped before completing its request.",
  agent_usage_limit: "The provider's usage limit stopped this step.",
  agent_auth_error: "The agent needs a working sign-in before it can continue.",
  agent_launch_error: "Relay could not start the selected agent.",
  model_unavailable_error:
    "The selected model is unavailable from the configured tools.",
  model_selection_rejected_error: "The agent rejected the selected model.",
  agent_configuration_error: "The agent rejected the requested configuration.",
  output_validation_error: "The step did not produce its required output.",
  loop_exhausted:
    "The loop reached its iteration limit without satisfying its stop condition. Open the step to inspect the retained results.",
  node_timeout: "The step reached its time limit.",
  worker_lost: "The worker stopped before finishing this step.",
  soft_denied: "The tool did not have permission to complete its work.",
  git_error: "A Git operation could not complete.",
  worktree_error: "Relay could not prepare or clean up the working folder.",
};

export function failureReason(
  problem: FailureDetails | null | undefined,
  subject?: "Job" | "Step",
): string {
  const message = problem?.message ?? problem?.error_message;
  if (message) return message;
  const reason =
    reasons[problem?.error_code ?? ""] ?? reasons[problem?.stop_reason ?? ""];
  if (reason) return reason;
  if (
    problem?.exit_code !== null &&
    problem?.exit_code !== undefined &&
    problem.exit_code !== 0
  ) {
    if (subject)
      return `${subject} failed with exit code ${problem.exit_code}.`;
    return `The tool exited with code ${problem.exit_code}. Open the step's activity for its output.`;
  }
  if (subject) return `${subject} failed.`;
  return "The step could not finish. Open its activity to inspect the cause.";
}
