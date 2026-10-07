import { Button, Menu, MenuItem, Stack } from "@mui/material";
import { useState, type Ref } from "react";
import type { RunDetail } from "../types";
import { ActionIcon } from "./ActionIcon";

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
  onRerunAll: () => void; onRerunFailed?: () => void; rerunAllRef: Ref<HTMLButtonElement>;
}) {
  const actions = runActions(run.status);
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  return <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
    {actions.pause && <Button variant="outlined" disabled={busy} onClick={onPause}>{run.dispatch_paused ? "Resume" : "Pause"}</Button>}
    {actions.cancel && <Button color="error" variant="outlined" disabled={busy} onClick={onCancel}>Cancel run</Button>}
    {actions.rerunAll && <Button ref={rerunAllRef} variant="outlined" disabled={busy} aria-haspopup="menu" aria-expanded={Boolean(anchor)} startIcon={<ActionIcon name="refresh" />} endIcon={<ActionIcon name="down" />} onClick={(event) => setAnchor(event.currentTarget)}>Re-run jobs</Button>}
    <Menu anchorEl={anchor} open={Boolean(anchor)} onClose={() => setAnchor(null)}>
      <MenuItem onClick={() => { setAnchor(null); onRerunAll(); }}>Re-run all jobs</MenuItem>
      {actions.rerunFailed && onRerunFailed && <MenuItem onClick={() => { setAnchor(null); onRerunFailed(); }}>Re-run failed jobs…</MenuItem>}
    </Menu>
  </Stack>;
}
