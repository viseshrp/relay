import { Button, MenuItem, Stack, TextField, Typography } from "@mui/material";

import { api, errorMessage } from "../api";
import { projectPath } from "../navigation";

import { WorkflowManagement } from "./WorkflowManagement";
import { type WorkflowEntry } from "./WorkflowSidebar";

import type { ActionsWorkflowWorkspaceState } from "./useActionsWorkflowWorkspace";
type ReadResponse1 = { workflows: WorkflowEntry[] };

export function WorkflowEditorHeader({
  state,
}: {
  state: ActionsWorkflowWorkspaceState;
}) {
  const {
    parsed,
    inventory,
    key,
    flush,
    setKey,
    setError,
    setCreate,
    save,
    disabled,
    lease,
    valid,
    text,
    saved,
    promptEdits,
    setLaunch,
    savedParsed,
    base,
    holder,
    props,
    setInventory,
    setNotice,
  } = state;
  return (
    <Stack
      component="section"
      aria-label="Workflow header"
      direction="row"
      spacing={1}
      sx={{ flexWrap: "wrap", gap: 1 }}
    >
      <Typography
        component="h1"
        variant="h5"
        sx={{ flex: "1 1 100%", overflowWrap: "anywhere" }}
      >
        {parsed.value?.name ||
          inventory.find((item) => item.key === key)?.name ||
          "Choose a workflow"}
      </Typography>
      <TextField
        select
        label="Workflow"
        value={key}
        onChange={async (event) => {
          try {
            await flush();
            setKey(event.target.value);
          } catch (e) {
            setError(errorMessage(e));
          }
        }}
        sx={{ minWidth: 220 }}
      >
        {inventory.map((item) => (
          <MenuItem key={item.key} value={item.key}>
            {item.name || item.key}
          </MenuItem>
        ))}
      </TextField>
      <Button onClick={() => setCreate(true)}>Create workflow</Button>
      <Button
        onClick={() => void save()}
        disabled={
          !lease ||
          !valid ||
          (text === saved && !Object.keys(promptEdits).length)
        }
      >
        Save
      </Button>
      {!disabled && (
        <Button
          variant="contained"
          onClick={() => setLaunch(true)}
          disabled={!savedParsed.value}
        >
          Run workflow
        </Button>
      )}
      <WorkflowManagement
        workflowKey={key}
        name={parsed.value?.name || key}
        baseHash={base}
        holder={holder.current}
        project={props.requestProject}
        disabled={disabled}
        onChanged={async (next) => {
          const result = await api<ReadResponse1>(
            projectPath("/api/workflows", props.requestProject),
          );
          setInventory(result.workflows);
          setKey(next ?? result.workflows[0]?.key ?? "");
          if (next === key) setNotice("Workflow availability updated.");
        }}
      />
    </Stack>
  );
}
