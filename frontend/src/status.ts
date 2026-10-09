export function statusPresentation(status: string): { label: string; tone: string; symbol: "check" | "cross" | "clock" | "pause" | "skip" | "circle" } {
  const labels: Record<string, string> = {
    pending: "Not started", ready: "Ready", dispatched: "Starting", running: "In progress", completing: "Merging and cleaning up",
    waiting: "Waiting", paused_wait: "Waiting", succeeded: "Complete",
    failed: "Needs attention", skipped: "Skipped", canceled: "Stopped", canceling: "Stopping",
    failing: "Finishing after an error", interrupted: "Resuming after restart",
    repairing: "Repairing", repair_stopped: "Repairs stopped",
  };
  const symbol = status === "succeeded" ? "check" : ["failed", "repair_stopped", "failing"].includes(status) ? "cross"
    : ["running", "completing", "repairing", "dispatched", "canceling"].includes(status) ? "clock"
      : ["waiting", "paused_wait"].includes(status) ? "pause" : ["skipped", "canceled"].includes(status) ? "skip" : "circle";
  return { label: labels[status] ?? status, symbol, tone: symbol === "check" ? "success" : symbol === "cross" ? "error" : symbol === "pause" ? "warning" : symbol === "clock" ? "active" : "muted" };
}
