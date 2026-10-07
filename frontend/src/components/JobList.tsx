import { Box, Button, Divider, IconButton, List, ListItem, ListItemButton, ListItemText, SvgIcon, Typography } from "@mui/material";
import type { RetryConfiguration, RunNode } from "../types";
import { stageLabel, statusLabel } from "../navigation";
import { jobDuration } from "../job";
import { jobListRows } from "../job-list";
import { choiceKey, type PendingChoice, type SettingsChoices } from "./usePendingChoices";

function statusIcon(status: string): string {
  if (status === "succeeded") return "✓";
  if (status === "failed" || status === "repair_stopped") return "✕";
  if (status === "running" || status === "repairing") return "◷";
  if (status === "waiting") return "!";
  return "○";
}

export function JobList({ nodes, selected, repairOwners, hasMore, onSelect, onMore, pendingChoices, onEdit, onCheck }: {
  nodes: RunNode[]; selected: string | null; repairOwners: Map<string, string>;
  hasMore: boolean; onSelect: (scope: string | null) => void; onMore: () => void;
  pendingChoices?: Record<string, PendingChoice>;
  onEdit?: (settings: RetryConfiguration, choices: SettingsChoices) => void;
  onCheck?: () => void;
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
      <List disablePadding>{group.map(({ node, depth, context }) => {
        const settings = pendingChoices && node.pending_settings;
        const loaded = settings ? pendingChoices?.[choiceKey(settings)] : undefined;
        return <ListItem key={node.scope_path} disablePadding sx={{ flexWrap: "wrap" }} secondaryAction={settings && <IconButton
          aria-label={`Edit ${stageLabel(node.scope_path)} settings`} disabled={!loaded?.ready}
          onClick={() => { if (loaded?.ready) onEdit?.(settings, loaded.ready); }}>
          <SvgIcon><path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zm17.71-10.04a1 1 0 0 0 0-1.42l-2.5-2.5a1 1 0 0 0-1.42 0l-1.96 1.96 3.75 3.75 2.13-1.79z" /></SvgIcon>
        </IconButton>}>
          <ListItemButton selected={node.scope_path === selected} data-job-scope={node.scope_path}
            onClick={() => onSelect(node.scope_path)} sx={{ pl: 2 + depth * 1.5, pr: settings ? 6 : 2 }}>
            <Box aria-hidden sx={{ mr: 1 }}>{statusIcon(node.status)}</Box>
            <ListItemText primary={stageLabel(node.scope_path)} secondary={`${statusLabel(node.status)} · ${jobDuration(node.started_at, node.ended_at)}${context ? ` · ${context}` : ""}`} />
          </ListItemButton>
          {settings && !loaded && <Typography variant="caption" role="status" sx={{ px: 2 }}>Loading {stageLabel(node.scope_path)} settings…</Typography>}
          {loaded?.error && <Box sx={{ px: 2 }}>
            <Typography variant="caption" role="alert">{loaded.error}</Typography>
            <Button aria-label={`Check ${stageLabel(node.scope_path)} settings again`} onClick={onCheck}>Check again</Button>
          </Box>}
        </ListItem>;
      })}</List>
    </Box>)}
    {rows.length === 0 && <Typography color="text.secondary" sx={{ p: 2 }}>Jobs will appear here when the run is prepared.</Typography>}
    {hasMore && <Button onClick={onMore}>Load more jobs</Button>}
  </Box>;
}
