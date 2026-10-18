import { Box, Button, Stack, Typography } from "@mui/material";
import { useEffect, useState } from "react";

import { api } from "../api";
import { countLabel } from "../count";
import type { RunChanges, RunDetail } from "../types";
import { TERMINAL_RUNS } from "./RunWorkspaceShared";

const SHOWN_FILES = 10;

function CopyCommand({ command }: { command: string }) {
  const [notice, setNotice] = useState<string | null>(null);
  async function copy(): Promise<void> {
    try {
      await navigator.clipboard.writeText(command);
      setNotice("Command copied.");
    } catch {
      setNotice("Could not copy. Select the command to copy it.");
    }
  }
  return (
    <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
      <Box component="code" className="mono-wrap">
        {command}
      </Box>
      <Button
        size="small"
        onClick={() => void copy()}
        aria-label={`Copy ${command}`}
      >
        Copy
      </Button>
      {notice && (
        <Typography variant="caption" role="status">
          {notice}
        </Typography>
      )}
    </Stack>
  );
}

/** Say where a finished run's committed code is and how to bring it in. */
export function RunResultLocation({ detail }: { detail: RunDetail }) {
  const [changes, setChanges] = useState<RunChanges | null>(null);
  const finished = TERMINAL_RUNS.has(detail.status);
  // A merged run already reports its merge commit in the summary.
  const unmerged =
    finished && detail.has_committed_changes && !detail.merged_commit;
  useEffect(() => {
    setChanges(null);
    if (!unmerged) return;
    const controller = new AbortController();
    void api<RunChanges>(`/api/runs/${detail.id}/changes`, {
      signal: controller.signal,
    })
      .then((value) => {
        if (!controller.signal.aborted) setChanges(value);
      })
      // The run branch may have been cleaned up; then there is nothing to say.
      .catch(() => undefined);
    return () => controller.abort();
  }, [detail.id, unmerged]);
  const files = changes?.files ?? [];
  if (!unmerged || !changes || !files.length) return null;
  const count = changes.files_truncated
    ? `More than ${files.length} files`
    : countLabel(files.length, "file");
  return (
    <Stack
      spacing={1}
      sx={{ mt: 2 }}
      component="section"
      aria-label="Where the code is"
    >
      <Typography variant="subtitle2">
        {count} changed on branch {detail.run_branch}.
      </Typography>
      <Box component="ul" sx={{ m: 0, pl: 3 }}>
        {files.slice(0, SHOWN_FILES).map((file) => (
          <li key={file}>
            <code>{file}</code>
          </li>
        ))}
      </Box>
      {files.length > SHOWN_FILES && (
        <Typography variant="body2" color="text.secondary">
          and {countLabel(files.length - SHOWN_FILES, "more file")}.
        </Typography>
      )}
      {detail.source_branch && (
        <CopyCommand command={`git switch ${detail.source_branch}`} />
      )}
      <CopyCommand command={`git merge --ff-only ${detail.run_branch}`} />
      <Typography variant="body2" color="text.secondary">
        To merge automatically next time, choose &quot;Merge into the active
        branch, then delete working copies&quot; under Advanced options when you
        run the workflow.
      </Typography>
    </Stack>
  );
}
