export function statusPresentation(status: string): {
  label: string;
  tone: string;
  symbol: "check" | "cross" | "clock" | "pause" | "skip" | "circle";
} {
  const labels: Record<string, string> = {
    pending: "Queued",
    ready: "Queued",
    dispatched: "Queued",
    running: "In progress",
    completing: "Merging and cleaning up",
    waiting: "Waiting for you",
    paused_wait: "Waiting for you",
    succeeded: "Succeeded",
    failed: "Failed",
    skipped: "Skipped",
    canceled: "Cancelled",
    canceling: "Cancelling",
    failing: "Finishing after an error",
    interrupted: "Resuming after restart",
    repairing: "Repairing",
    repair_stopped: "Repairs stopped",
  };
  const symbol =
    status === "succeeded"
      ? "check"
      : ["failed", "repair_stopped", "failing"].includes(status)
        ? "cross"
        : [
              "running",
              "completing",
              "repairing",
              "dispatched",
              "canceling",
            ].includes(status)
          ? "clock"
          : ["waiting", "paused_wait"].includes(status)
            ? "pause"
            : ["skipped", "canceled"].includes(status)
              ? "skip"
              : "circle";
  return {
    label: labels[status] ?? status,
    symbol,
    tone:
      symbol === "check"
        ? "success"
        : symbol === "cross"
          ? "error"
          : symbol === "pause"
            ? "warning"
            : symbol === "clock"
              ? "active"
              : "muted",
  };
}
