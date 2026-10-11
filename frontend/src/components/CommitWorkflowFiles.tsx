import { countLabel } from "../count";
import {
  Alert,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  Stack,
  Typography,
} from "@mui/material";
import { useState } from "react";
import { api, errorMessage } from "../api";
import { projectPath } from "../navigation";

interface Preview {
  head: string;
  files: Array<{ path: string; hash: string; text: string }>;
  notices: string[];
}

export function CommitWorkflowFiles({
  workflowKey,
  project,
  onCommitted,
}: {
  workflowKey: string;
  project: string | null;
  onCommitted: () => void;
}) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [error, setError] = useState("");
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const path = projectPath(
    `/api/workflows/${workflowKey.split("/").map(encodeURIComponent).join("/")}/commit`,
    project,
  );
  async function review() {
    setBusy(true);
    setError("");
    setConfirmed(false);
    try {
      setPreview(await api<Preview>(path));
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }
  async function commit() {
    if (!preview || !confirmed) return;
    setBusy(true);
    setError("");
    try {
      await api(path, {
        method: "POST",
        body: JSON.stringify({
          confirmed: true,
          head: preview.head,
          hashes: Object.fromEntries(
            preview.files.map((file) => [file.path, file.hash]),
          ),
        }),
      });
      setPreview(null);
      onCommitted();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Button disabled={busy} onClick={() => void review()}>
        Commit workflow files
      </Button>
      {!preview && error && <Alert severity="error">{error}</Alert>}
      <Dialog
        open={Boolean(preview)}
        onClose={() => {
          if (!busy) setPreview(null);
        }}
        fullWidth
        maxWidth="md"
      >
        <DialogTitle>Review workflow files to commit</DialogTitle>
        <DialogContent>
          <Stack spacing={2}>
            <Typography>
              This adds the files below to this project's Git history. Run
              history stays available.
            </Typography>
            {preview?.files.map((file) => (
              <Stack key={file.path}>
                <Typography component="h3" variant="subtitle1">
                  {file.path}
                </Typography>
                <Typography
                  component="pre"
                  sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
                >
                  {file.text}
                </Typography>
              </Stack>
            ))}
            {preview?.notices.map((notice) => (
              <Alert key={notice} severity="warning">
                {notice}
              </Alert>
            ))}
            {!preview?.files.length && (
              <Alert severity="info">
                No validated workflow files are available to commit. Review the
                other blocking changes in your project.
              </Alert>
            )}
            <FormControlLabel
              control={
                <Checkbox
                  checked={confirmed}
                  onChange={(event) => setConfirmed(event.target.checked)}
                />
              }
              label={`Commit ${countLabel(preview?.files.length ?? 0, "reviewed file")}`}
            />
            {error && <Alert severity="error">{error}</Alert>}
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button disabled={busy} onClick={() => setPreview(null)}>
            Cancel
          </Button>
          <Button
            variant="contained"
            disabled={busy || !confirmed || !preview?.files.length}
            onClick={() => void commit()}
          >
            {busy ? "Committing…" : "Confirm commit"}
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
