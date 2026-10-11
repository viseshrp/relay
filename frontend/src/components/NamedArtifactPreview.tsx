import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import { projectPath } from "../navigation";
import { SafeMarkdown } from "./SafeMarkdown";

type Preview = {
  files: Array<{ path: string; bytes: number }>;
  next: number | null;
  path: string;
  text: string;
  previewable: boolean;
  truncated: boolean;
  media_type: string;
};
export function NamedArtifactPreview({
  id,
  name,
  project,
  onClose,
}: {
  id: string;
  name: string;
  project: string;
  onClose: () => void;
}) {
  const [preview, setPreview] = useState<Preview | null>(null);
  const [path, setPath] = useState("");
  const [error, setError] = useState("");
  const endpoint = projectPath(
    `/api/workflow-artifacts/${id}/preview`,
    project,
  );
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    void api<Preview>(`${endpoint}&path=${encodeURIComponent(path)}`, {
      signal: controller.signal,
    })
      .then((next) =>
        setPreview((current) =>
          current
            ? {
                ...next,
                next: current.next,
                files: Array.from(
                  new Map(
                    [...current.files, ...next.files].map((item) => [
                      item.path,
                      item,
                    ]),
                  ).values(),
                ),
              }
            : next,
        ),
      )
      .catch((caught) => {
        if (!controller.signal.aborted) setError(errorMessage(caught));
      });
    return () => controller.abort();
  }, [endpoint, path]);
  async function more() {
    try {
      const next = await api<Preview>(
        `${endpoint}&offset=${preview?.next}&path=${encodeURIComponent(path)}`,
      );
      setPreview((current) =>
        current
          ? {
              ...next,
              files: Array.from(
                new Map(
                  [...current.files, ...next.files].map((item) => [
                    item.path,
                    item,
                  ]),
                ).values(),
              ),
            }
          : next,
      );
    } catch (caught) {
      setError(errorMessage(caught));
    }
  }
  return (
    <Dialog
      open
      fullWidth
      maxWidth="md"
      onClose={onClose}
      aria-labelledby="named-artifact-title"
    >
      <DialogTitle id="named-artifact-title">{name}</DialogTitle>
      <DialogContent>
        <Stack spacing={2}>
          {error && <Alert severity="error">{error}</Alert>}
          {!preview && !error && (
            <Typography role="status">Loading retained files…</Typography>
          )}
          {preview && (
            <>
              <TextField
                select
                label="Retained file"
                value={preview.path}
                onChange={(event) => setPath(event.target.value)}
              >
                {preview.files.map((item) => (
                  <MenuItem key={item.path} value={item.path}>
                    {item.path} · {item.bytes.toLocaleString()} B
                  </MenuItem>
                ))}
              </TextField>
              {preview.next !== null && (
                <Button onClick={() => void more()}>
                  Load more retained files
                </Button>
              )}
              {preview.previewable ? (
                /\.md$/i.test(preview.path) ? (
                  <SafeMarkdown text={preview.text} />
                ) : (
                  <Box component="pre" className="review-preview">
                    {preview.text || "Empty file."}
                  </Box>
                )
              ) : (
                <Typography>Download this binary file to view it.</Typography>
              )}
              {preview.truncated && (
                <Alert severity="info">
                  This preview is shortened. Download the complete artifact
                  before reviewing it.
                </Alert>
              )}
            </>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button
          component="a"
          href={projectPath(`/api/workflow-artifacts/${id}/download`, project)}
          download
        >
          Download
        </Button>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
