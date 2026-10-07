import { Box, Button, Divider, List, ListItemButton, ListItemText, Typography } from "@mui/material";
import type { RunNode } from "../types";
import { stageLabel, statusLabel } from "../navigation";
import { jobDuration } from "../job";
import { jobListRows } from "../job-list";

function statusIcon(status: string): string {
  if (status === "succeeded") return "✓";
  if (status === "failed" || status === "repair_stopped") return "✕";
  if (status === "running" || status === "repairing") return "◷";
  if (status === "waiting") return "!";
  return "○";
}

export function JobList({ nodes, selected, repairOwners, hasMore, onSelect, onMore }: {
  nodes: RunNode[]; selected: string | null; repairOwners: Map<string, string>;
  hasMore: boolean; onSelect: (scope: string | null) => void; onMore: () => void;
}) {
  const rows = jobListRows(nodes, repairOwners);
  const attention = rows.filter((row) => row.attention);
  const other = rows.filter((row) => !row.attention);
  return <Box component="nav" aria-label="Jobs">
    <Divider />
    <Typography variant="h6" sx={{ p: 2 }}>Jobs</Typography>
    <ListItemButton selected={!selected} onClick={() => onSelect(null)}><ListItemText primary="Summary" /></ListItemButton>
    {[attention, other].filter((group) => group.length > 0).map((group) => <Box key={group === attention ? "attention" : "jobs"}>
      {attention.length > 0 && <Typography variant="subtitle2" sx={{ px: 2, pt: 1 }}>{group === attention ? "Waiting and failed jobs" : "Other jobs"}</Typography>}
      <List disablePadding>{group.map(({ node, depth, context }) => <ListItemButton key={node.scope_path} selected={node.scope_path === selected}
        data-job-scope={node.scope_path} onClick={() => onSelect(node.scope_path)} sx={{ pl: 2 + depth * 1.5 }}>
        <Box aria-hidden sx={{ mr: 1 }}>{statusIcon(node.status)}</Box>
        <ListItemText primary={stageLabel(node.scope_path)} secondary={`${statusLabel(node.status)} · ${jobDuration(node.started_at, node.ended_at)}${context ? ` · ${context}` : ""}`} />
      </ListItemButton>)}</List>
    </Box>)}
    {rows.length === 0 && <Typography color="text.secondary" sx={{ p: 2 }}>Jobs will appear here when the run is prepared.</Typography>}
    {hasMore && <Button onClick={onMore}>Load more jobs</Button>}
  </Box>;
}
