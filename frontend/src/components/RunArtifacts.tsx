import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  Typography,
} from "@mui/material";
import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import { visibleArtifacts } from "../artifacts";
import { stageLabel } from "../navigation";
import type { ArtifactRecord } from "../types";
import { SafeMarkdown } from "./SafeMarkdown";

function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes.toLocaleString()} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function ArtifactPreview({
  artifact,
  onClose,
}: {
  artifact: ArtifactRecord;
  onClose: () => void;
}) {
  const [preview, setPreview] = useState<{
    text: string;
    truncated: boolean;
    previewable: boolean;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const controller = new AbortController();
    void api<typeof preview>(`/api/artifacts/${artifact.id}/preview`, {
      signal: controller.signal,
    })
      .then(setPreview)
      .catch((caught) => {
        if (!controller.signal.aborted) setError(errorMessage(caught));
      });
    return () => controller.abort();
  }, [artifact.id]);
  return (
    <Dialog
      open
      fullWidth
      maxWidth="md"
      onClose={onClose}
      aria-labelledby="artifact-preview-title"
    >
      <DialogTitle id="artifact-preview-title">{artifact.name}</DialogTitle>
      <DialogContent>
        {error && <Alert severity="error">{error}</Alert>}
        {!preview && !error && (
          <Typography role="status">Loading preview…</Typography>
        )}
        {preview &&
          (preview.previewable ? (
            /\.md$/i.test(artifact.name) ||
            /markdown/.test(artifact.media_type) ? (
              <SafeMarkdown text={preview.text} />
            ) : (
              <Box component="pre" className="review-preview">
                {preview.text || "Empty file."}
              </Box>
            )
          ) : (
            <Typography>Download this binary file to view it.</Typography>
          ))}
        {preview?.truncated && (
          <Alert severity="info">
            This preview is shortened. Download the complete file before
            reviewing it.
          </Alert>
        )}
      </DialogContent>
      <DialogActions>
        <Button component="a" href={`/api/artifacts/${artifact.id}`} download>
          Download
        </Button>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}

export function RunArtifacts({
  runId,
  artifacts,
  more,
  onMore,
}: {
  runId: string;
  artifacts: ArtifactRecord[];
  more: boolean;
  onMore: () => void;
}) {
  const [selected, setSelected] = useState<ArtifactRecord | null>(null);
  const visible = visibleArtifacts(artifacts);
  return (
    <Paper
      variant="outlined"
      className="section-card artifacts-section"
      id="run-artifacts"
      aria-label="Artifacts"
    >
      <Stack
        direction="row"
        sx={{ alignItems: "center", justifyContent: "space-between", mb: 1 }}
      >
        <Typography component="h2" variant="h6">
          Artifacts
        </Typography>
        {
          <Button
            component="a"
            href={`/api/runs/${runId}/artifacts/download`}
            download
          >
            Download all
          </Button>
        }
      </Stack>
      {visible.length ? (
        <TableContainer>
          <Table size="small" aria-label="Retained artifacts">
            <TableHead>
              <TableRow>
                <TableCell>Name</TableCell>
                <TableCell>Job</TableCell>
                <TableCell>Created</TableCell>
                <TableCell>Size</TableCell>
                <TableCell>Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {visible.map((artifact) => (
                <TableRow key={artifact.id}>
                  <TableCell data-label="Name">
                    <Typography variant="body2">{artifact.name}</Typography>
                    <Box component="details">
                      <Box component="summary">File details</Box>
                      <Typography variant="caption" className="mono-wrap">
                        {artifact.source_path}
                        <br />
                        Attempt {artifact.attempt_number} · SHA-256:{" "}
                        {artifact.sha256}
                      </Typography>
                    </Box>
                  </TableCell>
                  <TableCell data-label="Job">
                    {stageLabel(artifact.scope_path)}
                  </TableCell>
                  <TableCell data-label="Created">
                    {artifact.created_at
                      ? new Date(artifact.created_at).toLocaleString()
                      : "Date unavailable"}
                  </TableCell>
                  <TableCell
                    data-label="Size"
                    title={`${artifact.bytes.toLocaleString()} bytes`}
                  >
                    {sizeLabel(artifact.bytes)}
                  </TableCell>
                  <TableCell data-label="Actions">
                    <Button
                      onClick={() => setSelected(artifact)}
                      aria-label={`Preview ${artifact.name}`}
                    >
                      Preview
                    </Button>
                    <Button
                      component="a"
                      href={`/api/artifacts/${artifact.id}`}
                      download
                      aria-label={`Download ${artifact.name}, ${stageLabel(artifact.scope_path)}, attempt ${artifact.attempt_number}`}
                    >
                      Download
                    </Button>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      ) : (
        <Typography color="text.secondary">
          No artifacts yet. Add relay/upload-artifact to a step to save a file.
        </Typography>
      )}
      {more && <Button onClick={onMore}>Load more artifacts</Button>}
      {selected && (
        <ArtifactPreview
          key={selected.id}
          artifact={selected}
          onClose={() => setSelected(null)}
        />
      )}
    </Paper>
  );
}
