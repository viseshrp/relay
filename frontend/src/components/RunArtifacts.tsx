import { Box, Button, Paper, Table, TableBody, TableCell, TableContainer, TableHead, TableRow, Typography } from "@mui/material";
import { stageLabel } from "../navigation";
import type { ArtifactRecord } from "../types";
import { HelpLabel } from "./HelpTip";

function sizeLabel(bytes: number): string {
  if (bytes < 1024) return `${bytes.toLocaleString()} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

export function RunArtifacts({ artifacts, more, onMore }: {
  artifacts: ArtifactRecord[]; more: boolean; onMore: () => void;
}) {
  return <Paper variant="outlined" className="section-card" id="run-artifacts" aria-label="Artifacts">
    <Typography variant="h6" sx={{ mb: 1 }}><HelpLabel topic="artifacts">Artifacts</HelpLabel></Typography>
    {artifacts.length ? <TableContainer><Table size="small" aria-label="Retained artifacts">
      <TableHead><TableRow><TableCell>Name</TableCell><TableCell>Job</TableCell><TableCell>Attempt</TableCell><TableCell>Size</TableCell><TableCell>Download</TableCell></TableRow></TableHead>
      <TableBody>{artifacts.map((artifact) => <TableRow key={artifact.id}>
        <TableCell><Typography variant="body2">{artifact.name}</Typography>
          <Box component="details"><Box component="summary">File details</Box><Typography variant="caption" className="mono-wrap">{artifact.source_path}<br />SHA-256: {artifact.sha256}</Typography></Box>
        </TableCell>
        <TableCell>{stageLabel(artifact.scope_path)}</TableCell>
        <TableCell>{artifact.attempt_number}</TableCell>
        <TableCell title={`${artifact.bytes.toLocaleString()} bytes`}>{sizeLabel(artifact.bytes)}</TableCell>
        <TableCell><Button component="a" href={`/api/artifacts/${encodeURIComponent(artifact.id)}`} download aria-label={`Download ${artifact.name}, ${stageLabel(artifact.scope_path)}, attempt ${artifact.attempt_number}`}>Download</Button></TableCell>
      </TableRow>)}</TableBody>
    </Table></TableContainer> : <Typography color="text.secondary">No preserved artifacts.</Typography>}
    {more && <Button onClick={onMore}>Load more artifacts</Button>}
  </Paper>;
}
