import { useState } from "react";
import { useClock } from "../useClock";
import { ActionIcon, StatusIcon } from "./ActionIcon";
import {
  Box,
  Button,
  Divider,
  IconButton,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  SvgIcon,
  Typography,
  Menu,
  MenuItem,
} from "@mui/material";
import type { RetryConfiguration, RunNode } from "../types";
import { stageLabel, statusLabel } from "../navigation";
import { jobDuration } from "../job";
import { jobListRows } from "../job-list";
import {
  choiceKey,
  type PendingChoice,
  type SettingsChoices,
} from "./usePendingChoices";

export function JobList({
  nodes,
  selected,
  repairOwners,
  hasMore,
  onSelect,
  onMore,
  pendingChoices,
  onEdit,
  onCheck,
}: {
  nodes: RunNode[];
  selected: string | null;
  repairOwners: Map<string, string>;
  hasMore: boolean;
  onSelect: (scope: string | null) => void;
  onMore: () => void;
  pendingChoices?: Record<string, PendingChoice>;
  onEdit?: (settings: RetryConfiguration, choices: SettingsChoices) => void;
  onCheck?: () => void;
}) {
  const [filter, setFilter] = useState("all");
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const now = useClock(
    nodes.some((node) =>
      ["running", "waiting", "repairing"].includes(node.status),
    ),
  );
  function href(scope: string | null) {
    const query = new URLSearchParams(window.location.search);
    if (scope) query.set("job", scope);
    else query.delete("job");
    return `/?${query}`;
  }
  const rows = jobListRows(nodes, repairOwners).filter(
    (row) =>
      filter === "all" ||
      (filter === "attention" ? row.attention : row.node.status === filter),
  );
  const attention = rows.filter((row) => row.attention);
  const other = rows.filter((row) => !row.attention);
  return (
    <Box component="nav" aria-label="Jobs">
      <ListItemButton
        component="a"
        href={href(null)}
        selected={!selected}
        onClick={(event) => {
          if (
            event.metaKey ||
            event.ctrlKey ||
            event.shiftKey ||
            event.altKey ||
            event.button !== 0
          )
            return;
          event.preventDefault();
          onSelect(null);
        }}
      >
        <ActionIcon name="summary" />
        <ListItemText primary="Summary" />
      </ListItemButton>
      <Box className="jobs-sidebar-heading">
        <Typography variant="body2">All jobs</Typography>
        <IconButton
          aria-label="Filter jobs"
          aria-haspopup="menu"
          onClick={(event) => setAnchor(event.currentTarget)}
        >
          <ActionIcon name="filter" />
        </IconButton>
      </Box>
      <Menu
        anchorEl={anchor}
        open={Boolean(anchor)}
        onClose={() => setAnchor(null)}
      >
        {[
          ["all", "All jobs"],
          ["attention", "Waiting and failed"],
          ["running", "In progress"],
          ["succeeded", "Succeeded"],
          ["skipped", "Skipped"],
        ].map(([value, label]) => (
          <MenuItem
            key={value}
            selected={filter === value}
            onClick={() => {
              setFilter(value);
              setAnchor(null);
            }}
          >
            {label}
          </MenuItem>
        ))}
      </Menu>
      <Divider />
      {[attention, other]
        .filter((group) => group.length > 0)
        .map((group) => (
          <Box key={group === attention ? "attention" : "jobs"}>
            {attention.length > 0 && (
              <Typography variant="subtitle2" sx={{ px: 2, pt: 1 }}>
                {group === attention ? "Waiting and failed jobs" : "Other jobs"}
              </Typography>
            )}
            <List disablePadding>
              {group.map(({ node, depth, context }) => {
                const label =
                  node.node_type.startsWith("actions_") && node.display_name
                    ? node.display_name
                    : stageLabel(node.scope_path);
                const settings = pendingChoices && node.pending_settings;
                const loaded = settings
                  ? pendingChoices?.[choiceKey(settings)]
                  : undefined;
                return (
                  <ListItem
                    key={node.scope_path}
                    disablePadding
                    sx={{ flexWrap: "wrap" }}
                    secondaryAction={
                      settings && (
                        <IconButton
                          aria-label={`Edit ${stageLabel(node.scope_path)} settings`}
                          disabled={!loaded?.ready}
                          onClick={() => {
                            if (loaded?.ready) onEdit?.(settings, loaded.ready);
                          }}
                        >
                          <SvgIcon>
                            <path d="M3 17.25V21h3.75L17.81 9.94l-3.75-3.75L3 17.25zm17.71-10.04a1 1 0 0 0 0-1.42l-2.5-2.5a1 1 0 0 0-1.42 0l-1.96 1.96 3.75 3.75 2.13-1.79z" />
                          </SvgIcon>
                        </IconButton>
                      )
                    }
                  >
                    <ListItemButton
                      component="a"
                      href={href(node.scope_path)}
                      aria-current={
                        node.scope_path === selected ? "page" : undefined
                      }
                      selected={node.scope_path === selected}
                      data-job-scope={node.scope_path}
                      onClick={(event) => {
                        if (
                          event.metaKey ||
                          event.ctrlKey ||
                          event.shiftKey ||
                          event.altKey ||
                          event.button !== 0
                        )
                          return;
                        event.preventDefault();
                        onSelect(node.scope_path);
                      }}
                      sx={{ pl: 1 + Math.min(depth, 2), pr: settings ? 6 : 2 }}
                    >
                      <span aria-hidden="true">
                        <StatusIcon status={node.status} />
                      </span>
                      <ListItemText
                        title={`${label}${context ? ` · ${context}` : ""}`}
                        primary={label}
                        secondary={
                          <span className="sr-only">
                            {statusLabel(node.status)} {context}
                            {node.matrix_index !== null &&
                            node.matrix_index !== undefined
                              ? ` · variant ${node.matrix_index + 1}`
                              : ""}
                          </span>
                        }
                      />
                      <Typography
                        variant="caption"
                        color="text.secondary"
                        className="sidebar-job-duration"
                        title={statusLabel(node.status)}
                      >
                        {node.started_at
                          ? jobDuration(node.started_at, node.ended_at, now)
                          : ""}
                      </Typography>
                    </ListItemButton>
                    {settings && !loaded && (
                      <Typography
                        variant="caption"
                        role="status"
                        sx={{ px: 2 }}
                      >
                        Loading {stageLabel(node.scope_path)} settings…
                      </Typography>
                    )}
                    {loaded?.error && (
                      <Box sx={{ px: 2 }}>
                        <Typography variant="caption" role="alert">
                          {loaded.error}
                        </Typography>
                        <Button
                          aria-label={`Check ${stageLabel(node.scope_path)} settings again`}
                          onClick={onCheck}
                        >
                          Check again
                        </Button>
                      </Box>
                    )}
                  </ListItem>
                );
              })}
            </List>
          </Box>
        ))}
      {rows.length === 0 && (
        <Typography color="text.secondary" sx={{ p: 2 }}>
          Jobs will appear here when the run is prepared.
        </Typography>
      )}
      {hasMore && <Button onClick={onMore}>Load more jobs</Button>}
    </Box>
  );
}
