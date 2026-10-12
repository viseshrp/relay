import { Alert, Box, Button, Stack, Typography } from "@mui/material";
import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";

import type { JobAttempt, JobChanges, RunEvent, RunJob } from "../types";
import { DiffViewer } from "./DiffViewer";

interface JobPage {
  job: RunJob;
  next: number | null;
}
interface EventPage {
  events: RunEvent[];
  next: number | null;
}
function mergeEvents(current: RunEvent[], incoming: RunEvent[]): RunEvent[] {
  return Array.from(
    new Map(
      [...current, ...incoming].map((event) => [event.id, event]),
    ).values(),
  ).sort((a, b) => a.id - b.id);
}
function JobChangesView({
  runId,
  scope,
  attempt,
}: {
  runId: string;
  scope: string;
  attempt: JobAttempt;
}) {
  const [changes, setChanges] = useState<JobChanges | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void api<JobChanges>(
      `/api/runs/${runId}/changes?job=${encodeURIComponent(scope)}&attempt=${attempt.number}`,
      { signal: controller.signal },
    )
      .then(setChanges)
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) setError(errorMessage(caught));
      });
    return () => controller.abort();
  }, [runId, scope, attempt.number, attempt.ending_head]);
  return (
    <Stack spacing={1}>
      {error && <Alert severity="error">{error}</Alert>}
      {!changes && !error && (
        <Typography>Loading this attempt's changes…</Typography>
      )}
      {changes && (
        <>
          {changes.commits.map((commit) => (
            <Box key={commit.sha} sx={{ minWidth: 0 }}>
              <Typography sx={{ overflowWrap: "anywhere" }}>
                {commit.title}
              </Typography>
              <Box component="details" sx={{ minWidth: 0, mt: 0.5 }}>
                <Box component="summary" sx={{ cursor: "pointer" }}>
                  Commit {commit.sha.slice(0, 7)}
                </Box>
                <Stack
                  direction="row"
                  spacing={1}
                  sx={{ alignItems: "center", mt: 0.5, flexWrap: "wrap" }}
                >
                  <Box
                    component="code"
                    sx={{
                      wordBreak: "break-all",
                      overflowWrap: "anywhere",
                      fontSize: "0.85rem",
                    }}
                  >
                    {commit.sha}
                  </Box>
                  <Button
                    size="small"
                    onClick={() =>
                      void navigator.clipboard?.writeText(commit.sha)
                    }
                    aria-label={`Copy commit ${commit.sha.slice(0, 7)}`}
                  >
                    Copy
                  </Button>
                </Stack>
              </Box>
            </Box>
          ))}
          {changes.commits.length >= 100 && (
            <Typography>Showing the latest 100 commits.</Typography>
          )}
          <DiffViewer
            text={changes.text}
            truncated={changes.truncated}
            finished={Boolean(attempt.ended_at)}
          />
        </>
      )}
    </Stack>
  );
}
export { type JobPage, type EventPage, mergeEvents, JobChangesView };
