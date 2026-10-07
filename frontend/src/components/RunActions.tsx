import { Button, Stack } from "@mui/material";
import type { Ref } from "react";
import type { RunDetail } from "../types";

export function runActions(status: string): { pause: boolean; cancel: boolean; rerunAll: boolean; rerunFailed: boolean } {
  return {
    pause: ["pending", "running", "paused_wait"].includes(status),
    cancel: ["running", "paused_wait"].includes(status),
    rerunAll: ["succeeded", "failed", "canceled"].includes(status),
    rerunFailed: status === "failed",
  };
}

export function RunActions({ run, busy, onPause, onCancel, onRerunAll, onRerunFailed, rerunAllRef }: {
  run: RunDetail; busy: boolean; onPause: () => void; onCancel: () => void;
  onRerunAll: () => void; onRerunFailed?: () => void;
  rerunAllRef: Ref<HTMLButtonElement>;
}) {
  const actions = runActions(run.status);
  return <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", rowGap: 1 }}>
    {actions.pause && <Button variant="outlined" disabled={busy} onClick={onPause}>{run.dispatch_paused ? "Resume" : "Pause"}</Button>}
    {actions.cancel && <Button color="error" variant="outlined" disabled={busy} onClick={onCancel}>Cancel run</Button>}
    {actions.rerunFailed && onRerunFailed && <Button variant="contained" disabled={busy} onClick={onRerunFailed}>Re-run failed jobs</Button>}
    {actions.rerunAll && <Button ref={rerunAllRef} variant="outlined" disabled={busy} onClick={onRerunAll}>Re-run all jobs</Button>}
  </Stack>;
}
