import { HelpLabel, HelpSelectField } from "./HelpTip";
import {
  Alert,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Stack,
  Typography,
} from "@mui/material";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage } from "../api";
import { statusLabel } from "../navigation";
import type { RunSummary } from "../types";
import { StatusIcon } from "./ActionIcon";
type ReadResponse1 = { removed: number };

const outcomes = ["succeeded", "failed", "canceled"] as const;
type Outcome = (typeof outcomes)[number];
type Cursors = Record<Outcome, string | null>;
interface RunPage {
  runs: RunSummary[];
  next: string | null;
}

export function TemporaryResourceCleanup({ projectId }: { projectId: string }) {
  const [runs, setRuns] = useState<RunSummary[]>([]);
  const [cursors, setCursors] = useState<Cursors>({
    succeeded: null,
    failed: null,
    canceled: null,
  });
  const [selectedId, setSelectedId] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const request = useRef<AbortController | null>(null);
  const selected = runs.find((run) => run.id === selectedId);

  const load = useCallback(
    async (older?: Cursors): Promise<void> => {
      request.current?.abort();
      const controller = new AbortController();
      request.current = controller;
      setLoading(true);
      setError(null);
      if (!older) {
        setSelectedId("");
        setRuns([]);
        setNotice(null);
      }
      try {
        // Separate bounded queries use the server's supported run-state filter.
        const pages = await Promise.all(
          outcomes.map(async (status) => {
            if (older && !older[status]) return { status, page: null };
            const query = new URLSearchParams({
              project: projectId,
              status,
              limit: "20",
            });
            const cursor = older?.[status];
            if (cursor) query.set("since", cursor);
            return {
              status,
              page: await api<RunPage>(`/api/runs?${query.toString()}`, {
                signal: controller.signal,
              }),
            };
          }),
        );
        if (controller.signal.aborted) return;
        const next: Cursors = { succeeded: null, failed: null, canceled: null };
        const incoming: RunSummary[] = [];
        for (const { status, page } of pages) {
          if (page) {
            incoming.push(...page.runs);
            next[status] = page.next;
          }
        }
        setRuns((current) =>
          [
            ...new Map(
              [...(older ? current : []), ...incoming].map((run) => [
                run.id,
                run,
              ]),
            ).values(),
          ].sort((left, right) => right.number - left.number),
        );
        setCursors(next);
      } catch (caught: unknown) {
        if (!controller.signal.aborted) setError(errorMessage(caught));
      } finally {
        if (!controller.signal.aborted) setLoading(false);
      }
    },
    [projectId],
  );

  useEffect(() => {
    void load();
    return () => request.current?.abort();
  }, [load]);

  async function clean(): Promise<void> {
    if (!selected) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api<ReadResponse1>(
        `/api/runs/${encodeURIComponent(selected.id)}/resources/clean`,
        { method: "POST", body: JSON.stringify({ confirm: true }) },
      );
      setNotice(
        result.removed === 0
          ? `No temporary folders remained for run #${selected.number}.`
          : `Removed ${result.removed} temporary ${result.removed === 1 ? "folder" : "folders"} for run #${selected.number}.`,
      );
      setOpen(false);
    } catch (caught: unknown) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Stack component="section" aria-label="Temporary run resources" spacing={2}>
      <Typography variant="h6">
        <HelpLabel topic="temporaryCleanup">Temporary run resources</HelpLabel>
      </Typography>
      <Typography variant="body2">
        Retry removal of leftover temporary folders for a completed run. Saved
        reports and working copies are kept.
      </Typography>
      {notice && <Alert severity="success">{notice}</Alert>}
      {error && !open && (
        <Alert
          severity="error"
          action={
            <Button disabled={loading || busy} onClick={() => void load()}>
              Reload completed runs
            </Button>
          }
        >
          {error}
        </Alert>
      )}
      {loading && (
        <CircularProgress size={24} aria-label="Loading completed runs" />
      )}
      {!loading && !error && runs.length === 0 && (
        <Typography>
          No completed runs are available for temporary cleanup in this project.
        </Typography>
      )}
      <HelpSelectField
        topic="temporaryCleanup"
        label="Completed run"
        fullWidth
        value={selectedId}
        renderValue={() =>
          selected
            ? `#${selected.number} ${selected.title} · ${statusLabel(selected.status)}`
            : runs.length
              ? "Choose a completed run"
              : "No completed runs"
        }
        disabled={loading || busy || runs.length === 0}
        onChange={(event) => {
          setSelectedId(event.target.value);
          setNotice(null);
          setError(null);
        }}
      >
        <MenuItem value="">
          {!loading && runs.length === 0
            ? "No completed runs"
            : "Choose a completed run"}
        </MenuItem>
        {runs.map((run) => (
          <MenuItem
            key={run.id}
            value={run.id}
            aria-label={`#${run.number} ${run.title} ${statusLabel(run.status)}`}
          >
            <Box component="span" className="run-choice">
              <StatusIcon status={run.status} />
              <span className="run-choice-number">#{run.number}</span>
              <span className="run-choice-title">{run.title}</span>
              <span className="run-choice-status">
                {statusLabel(run.status)}
              </span>
            </Box>
          </MenuItem>
        ))}
      </HelpSelectField>
      <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: "wrap" }}>
        <Button
          variant="outlined"
          disabled={!selected || loading || busy}
          onClick={() => {
            setError(null);
            setOpen(true);
          }}
        >
          Retry temporary resource cleanup
        </Button>
        <Button disabled={loading || busy} onClick={() => void load()}>
          Refresh completed runs
        </Button>
        {Object.values(cursors).some(Boolean) && (
          <Button disabled={loading || busy} onClick={() => void load(cursors)}>
            Load older completed runs
          </Button>
        )}
      </Stack>
      <Dialog
        open={open}
        onClose={() => {
          if (!busy) setOpen(false);
        }}
        fullWidth
        aria-labelledby="resource-cleanup-title"
      >
        <DialogTitle id="resource-cleanup-title">
          Retry temporary cleanup for run #{selected?.number}?
        </DialogTitle>
        <DialogContent>
          <Stack spacing={2}>
            <Typography>{selected?.title}</Typography>
            <Typography>
              Remove leftover Relay-owned attempt folders for this run. Reports,
              code, run history, credentials, and personal browser profiles stay
              in place. Relay checks the run and attempt ownership again before
              deleting anything.
            </Typography>
            {error && <Alert severity="error">{error}</Alert>}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button disabled={busy} onClick={() => setOpen(false)}>
            Cancel
          </Button>
          <Button
            variant="contained"
            disabled={busy || !selected}
            onClick={() => void clean()}
          >
            {busy ? "Cleaning…" : "Confirm temporary cleanup"}
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}
