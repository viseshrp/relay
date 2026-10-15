import { Button, MenuItem, Stack, TextField, Typography } from "@mui/material";

import { errorMessage } from "../api";

import { WorkflowManagement } from "./WorkflowManagement";

import type { ActionsWorkflowWorkspaceState } from "./useActionsWorkflowWorkspace";

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
    refresh,
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
        title={
          parsed.value?.name ||
          inventory.find((item) => item.key === key)?.name ||
          "Choose a workflow"
        }
        sx={{ flex: "1 1 100%", overflowWrap: "anywhere" }}
      >
        <span className="run-title">
          {parsed.value?.name ||
            inventory.find((item) => item.key === key)?.name ||
            "Choose a workflow"}
        </span>
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
          const workflows = await refresh();
          if (!workflows) return;
          setKey(next ?? workflows[0]?.key ?? "");
          if (next === key) setNotice("Workflow availability updated.");
        }}
      />
    </Stack>
  );
}
