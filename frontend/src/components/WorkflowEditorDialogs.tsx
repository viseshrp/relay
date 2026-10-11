import {
  Box,
  Button,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Drawer,
  FormControlLabel,
  Menu,
  MenuItem,
  Stack,
  Typography,
} from "@mui/material";

import { moveActionStep, launchView } from "../actions-workflow";

import { CreateWorkflowDialog } from "./CreateWorkflowDialog";
import { LaunchPanel } from "./LaunchPanel";

import { ActionJobEditor } from "./ActionJobEditor";

import { sourceDiff } from "../source-format";

import type { ActionsWorkflowWorkspaceState } from "./useActionsWorkflowWorkspace";
export function WorkflowEditorDialogs({
  state,
}: {
  state: ActionsWorkflowWorkspaceState;
}) {
  const {
    drawer,
    job,
    setDrawer,
    removeJob,
    jobId,
    parsed,
    manifest,
    index,
    setIndex,
    change,
    setText,
    text,
    agents,
    providerDefaults,
    defaultModel,
    props,
    key,
    promptEdits,
    setPromptEdits,
    contextMenu,
    setContextMenu,
    duplicateJob,
    runFromJob,
    formatted,
    setFormatted,
    holder,
    create,
    setCreate,
    setKey,
    refresh,
    startJob,
    launch,
    savedParsed,
    environments,
    saved,
    setLaunch,
    activation,
    setActivation,
    setAuthorize,
    authorize,
    toggleTrigger,
    save,
    lease,
    valid,
  } = state;
  return (
    <>
      <Drawer
        anchor="right"
        open={drawer && Boolean(job)}
        onClose={() => setDrawer(false)}
        slotProps={{
          paper: {
            sx: { width: { xs: "100%", sm: 520 }, maxWidth: "100vw", p: 2 },
          },
        }}
      >
        <Stack spacing={2}>
          <Typography component="h2" variant="h6">
            Job settings
          </Typography>
          <Stack direction="row">
            <Button onClick={() => setDrawer(false)}>Close job settings</Button>
            <Button
              disabled={
                !lease ||
                !valid ||
                (text === saved && !Object.keys(promptEdits).length)
              }
              onClick={() => {
                setDrawer(false);
                void save();
              }}
            >
              Save
            </Button>
            <Button onClick={() => removeJob(jobId)}>Remove job</Button>
          </Stack>
          {job && parsed.value && manifest && (
            <ActionJobEditor
              workflow={parsed.value}
              jobId={jobId}
              index={index}
              onIndex={setIndex}
              manifest={manifest}
              change={change}
              onMove={(from, to) => {
                setText(moveActionStep(text, jobId, from, to));
                setIndex(to);
              }}
              agents={agents}
              defaults={providerDefaults}
              defaultModel={defaultModel}
              project={props.requestProject}
              workflowKey={key}
              edits={promptEdits}
              onEdits={(reference, edit) =>
                setPromptEdits((current) => ({
                  ...current,
                  [reference]: edit,
                }))
              }
            />
          )}
        </Stack>
      </Drawer>
      <Menu
        open={Boolean(contextMenu)}
        onClose={() => setContextMenu(null)}
        anchorReference="anchorPosition"
        anchorPosition={
          contextMenu ? { left: contextMenu.x, top: contextMenu.y } : undefined
        }
      >
        <MenuItem
          onClick={() => {
            if (contextMenu) duplicateJob(contextMenu.id);
          }}
        >
          Duplicate job
        </MenuItem>
        <MenuItem
          onClick={() => {
            if (contextMenu) removeJob(contextMenu.id);
          }}
        >
          Delete job
        </MenuItem>
        <MenuItem
          onClick={() => {
            if (contextMenu) void runFromJob(contextMenu.id);
          }}
        >
          Run from here
        </MenuItem>
      </Menu>
      <Dialog
        open={formatted !== null}
        onClose={() => setFormatted(null)}
        fullWidth
        maxWidth="md"
      >
        <DialogTitle>Preview YAML formatting</DialogTitle>
        <DialogContent>
          <Box
            component="pre"
            sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
          >
            {sourceDiff(text, formatted ?? text)}
          </Box>
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setFormatted(null)}>Cancel</Button>
          <Button
            onClick={() => {
              if (formatted !== null) setText(formatted);
              setFormatted(null);
            }}
          >
            Apply formatting
          </Button>
        </DialogActions>
      </Dialog>
      <CreateWorkflowDialog
        holder={holder.current}
        open={create}
        requestProject={props.requestProject}
        onClose={() => setCreate(false)}
        onCreated={async (newKey) => {
          setCreate(false);
          setKey(newKey);
          await refresh();
        }}
      />
      <LaunchPanel
        initialEntryPoint={startJob}
        open={launch}
        workflowKey={key}
        workflow={launchView(savedParsed.value, environments)}
        project={props.project}
        requestProject={props.requestProject}
        modelOptions={[]}
        blockedReason={
          !savedParsed.value ? "Choose a valid saved workflow." : null
        }
        saveError={null}
        draftNotice={
          text !== saved || Object.keys(promptEdits).length
            ? "Your unsaved draft is not included. This runs the saved workflow."
            : null
        }
        onClose={() => {
          setLaunch(false);
          props.onLaunchClosed();
        }}
        onExited={() => undefined}
        onRunLaunched={props.onRunLaunched}
        previousRun={null}
      />
      <Dialog
        open={Boolean(activation)}
        onClose={() => {
          setActivation(null);
          setAuthorize(false);
        }}
      >
        <DialogTitle>Activate {activation}</DialogTitle>
        <DialogContent>
          <FormControlLabel
            control={
              <Checkbox
                checked={authorize}
                onChange={(e) => setAuthorize(e.target.checked)}
              />
            }
            label="Allow this trigger to launch writing jobs automatically on this computer."
          />
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setActivation(null)}>Cancel</Button>
          <Button
            disabled={!authorize || text !== saved}
            onClick={() => {
              if (activation) void toggleTrigger(activation, true);
            }}
          >
            Activate trigger
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
