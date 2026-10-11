import {
  Box,
  Button,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Typography,
} from "@mui/material";
import { viewHref } from "../navigation";
import { ActionIcon, StatusIcon } from "./ActionIcon";

export interface WorkflowEntry {
  key: string;
  name: string;
  disabled?: boolean;
  last_status?: string;
  last_run?: string;
}

export function WorkflowSidebar({
  workflows,
  selected,
  project,
  editor = false,
  onSelect,
  onCreate,
}: {
  workflows: WorkflowEntry[];
  selected: string;
  project: string;
  editor?: boolean;
  onSelect: (key: string) => void;
  onCreate: () => void;
}) {
  return (
    <Box
      component="nav"
      aria-label="Workflow sidebar"
      className="actions-sidebar"
    >
      <Typography component="h2" variant="h6" sx={{ p: 2 }}>
        Workflows
      </Typography>
      <Button fullWidth variant="outlined" onClick={onCreate}>
        New workflow
      </Button>
      <List>
        <ListItem disablePadding>
          <ListItemButton
            component="a"
            href={viewHref("runs", project)}
            selected={!selected}
            onClick={(event) => {
              if (!event.metaKey && !event.ctrlKey && event.button === 0) {
                event.preventDefault();
                onSelect("");
              }
            }}
          >
            <ActionIcon name="workflow" />
            <ListItemText primary="All workflows" />
          </ListItemButton>
        </ListItem>
        {workflows.map((workflow) => (
          <ListItem key={workflow.key} disablePadding>
            <ListItemButton
              component="a"
              href={viewHref(editor ? "workflows" : "runs", project, {
                workflow: workflow.key,
              })}
              selected={selected === workflow.key}
              title={`${workflow.name}\n${workflow.key}`}
              onClick={(event) => {
                if (!event.metaKey && !event.ctrlKey && event.button === 0) {
                  event.preventDefault();
                  onSelect(workflow.key);
                }
              }}
            >
              {workflow.last_status ? (
                <StatusIcon status={workflow.last_status} />
              ) : (
                <ActionIcon name="workflow" />
              )}
              <ListItemText
                primary={workflow.name}
                secondary={`${workflow.key}${workflow.disabled ? " · Disabled" : ""}`}
                slotProps={{
                  primary: { noWrap: true },
                  secondary: { sx: { overflowWrap: "anywhere" } },
                }}
              />
            </ListItemButton>
          </ListItem>
        ))}
      </List>
    </Box>
  );
}
