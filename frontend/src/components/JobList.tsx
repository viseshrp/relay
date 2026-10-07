import { Box, Button, Divider, List, ListItemButton, ListItemText, Typography } from "@mui/material";
import type { RunNode } from "../types";
import { stageLabel, statusLabel } from "../navigation";
import { jobDuration } from "../job";

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
  const groups = new Map<string, RunNode[]>();
  for (const node of nodes) {
    if (node.node_type === "loop" && /#\d+$/.test(node.scope_path)) continue;
    const parent = node.parent_scope ?? "root";
    const group = groups.get(parent) ?? [];
    group.push(node); groups.set(parent, group);
  }
  return <Box component="nav" aria-label="Jobs">
    <Divider />
    <Typography variant="h6" sx={{ p: 2 }}>Jobs</Typography>
    <ListItemButton selected={!selected} onClick={() => onSelect(null)}><ListItemText primary="Summary" /></ListItemButton>
    {Array.from(groups, ([parent, rows]) => <Box key={parent}>
      {parent !== "root" && <Typography variant="subtitle2" sx={{ px: 2, pt: 1 }}>
        {repairOwners.get(parent) ? `Repair for ${stageLabel(repairOwners.get(parent) ?? parent)} · ` : ""}{stageLabel(parent)}
      </Typography>}
      <List disablePadding>{rows.map((node) => <ListItemButton key={node.id} selected={node.scope_path === selected}
        onClick={() => onSelect(node.scope_path)} sx={{ pl: parent === "root" ? 2 : 3 }}>
        <Box aria-hidden sx={{ mr: 1 }}>{statusIcon(node.status)}</Box>
        <ListItemText primary={stageLabel(node.scope_path)} secondary={`${statusLabel(node.status)} · ${jobDuration(node.started_at, node.ended_at)}`} />
      </ListItemButton>)}</List>
    </Box>)}
    {hasMore && <Button onClick={onMore}>Load more jobs</Button>}
  </Box>;
}
