import { ActionIcon } from "./ActionIcon";
import { HelpTextField, HelpSelectField } from "./HelpTip";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  MenuItem,
  Stack,
  Typography,
} from "@mui/material";

import { stageLabel } from "../navigation";

import { LaunchInputs } from "./LaunchInputs";
import { LaunchPreflight } from "./LaunchPreflight";

import type { LaunchPanelState } from "./useLaunchPanel";
export function LaunchPanelView({ state }: { state: LaunchPanelState }) {
  const {
    open,
    onClose,
    launching,
    onExited,
    launch,
    workflow,
    previousRun,
    draftNotice,
    source,
    cleanup,
    defaultCleanup,
    sourceError,
    reason,
    setSourceRevision,
    blockedReason,
    onSave,
    saveError,
    launchError,
    workflowKey,
    requestProject,
    preflight,
    preflightError,
    inputs,
    inputErrors,
    setInputs,
    setInputErrors,
    model,
    setModel,
    modelOptions,
    setCleanup,
    entryPoint,
    setEntryPoint,
  } = state;
  return (
    <Dialog
      open={open}
      onClose={() => {
        if (!launching) onClose();
      }}
      fullWidth
      maxWidth="sm"
      slotProps={{ transition: { onExited } }}
      aria-labelledby="launch-title"
    >
      <DialogTitle id="launch-title">Run workflow</DialogTitle>
      <form
        noValidate
        onSubmit={(event) => {
          event.preventDefault();
          void launch();
        }}
      >
        <DialogContent>
          <Stack spacing={2}>
            <Typography variant="h6">
              {workflow?.name ?? "Choose a workflow"}
            </Typography>
            {previousRun && (
              <Alert severity="info">
                Previous inputs are prefilled. This creates a new run using the
                saved workflow, current branch, and fresh agent checks. Changed
                input definitions are validated again.
              </Alert>
            )}
            {draftNotice && <Alert severity="info">{draftNotice}</Alert>}
            {source?.commit && (
              <Typography>
                Runs on a new branch from{" "}
                <strong>
                  {source.branch ?? `commit ${source.commit.slice(0, 12)}`}
                </strong>
                .
              </Typography>
            )}
            {(cleanup || defaultCleanup) === "merge_on_success" && (
              <Alert severity="info">
                After every job succeeds, Relay will fast-forward{" "}
                {source?.branch ?? "the branch selected at launch"} and delete
                the run working copies. The checkout must stay completely clean
                and on that branch.
              </Alert>
            )}
            {sourceError && <Alert severity="error">{sourceError}</Alert>}
            {reason && (
              <Alert
                severity="info"
                action={
                  sourceError ? (
                    <Button
                      onClick={() => setSourceRevision((value) => value + 1)}
                    >
                      Check again
                    </Button>
                  ) : blockedReason && onSave ? (
                    <Button onClick={onSave}>Save</Button>
                  ) : undefined
                }
              >
                {reason}
              </Alert>
            )}
            {saveError && <Alert severity="error">{saveError}</Alert>}
            {launchError && <Alert severity="error">{launchError}</Alert>}
            {!blockedReason && (
              <LaunchPreflight
                workflowKey={workflowKey}
                project={requestProject}
                result={preflight}
                error={preflightError}
                onCheck={() => setSourceRevision((value) => value + 1)}
              />
            )}
            <LaunchInputs
              definitions={workflow?.inputs ?? {}}
              values={inputs}
              errors={inputErrors}
              onChange={(name, value) => {
                setInputs((current) => ({ ...current, [name]: value }));
                setInputErrors((current) => {
                  const next = { ...current };
                  delete next[name];
                  return next;
                });
              }}
            />
            <Accordion>
              <AccordionSummary expandIcon={<ActionIcon name="down" />}>
                Advanced options
              </AccordionSummary>
              <AccordionDetails>
                <Stack spacing={2}>
                  <HelpTextField
                    topic="model"
                    label="Override model for this run"
                    placeholder="Use workflow, project, and global defaults"
                    value={model}
                    onChange={(event) => setModel(event.target.value)}
                    helperText="Leave blank to use the workflow, project, or global model. Values must match the provider exactly, including case."
                    slotProps={{ htmlInput: { list: "launch-model-options" } }}
                  />
                  <datalist id="launch-model-options">
                    {modelOptions.map((value) => (
                      <option key={value} value={value} />
                    ))}
                  </datalist>
                  <HelpSelectField
                    topic="cleanup"
                    label="After a successful run"
                    fullWidth
                    value={cleanup}
                    onChange={(event) => setCleanup(event.target.value)}
                    helperText={
                      <>
                        {" "}
                        {cleanup === "merge_on_success"
                          ? "Fast-forwards the branch shown above after every job succeeds. Commit all workflow, report, and code changes first. Dirty, switched, or diverged branches fail and keep the run working copy."
                          : "Saved reports and committed changes remain available after the working copy is deleted."}{" "}
                      </>
                    }
                  >
                    <MenuItem value="">
                      Use project and global defaults
                    </MenuItem>
                    <MenuItem value="clean_on_success">
                      Delete the working copy
                    </MenuItem>
                    <MenuItem value="retain">Keep the working copy</MenuItem>
                    <MenuItem value="merge_on_success">
                      Merge into the active branch, then delete working copies
                    </MenuItem>
                  </HelpSelectField>
                  {(workflow?.entrypoints?.length ?? 0) > 0 && (
                    <HelpSelectField
                      topic="entry"
                      label="Start from job"
                      fullWidth
                      value={entryPoint}
                      onChange={(event) => setEntryPoint(event.target.value)}
                      helperText={
                        <>
                          {" "}
                          Only jobs declared as start points are listed. Relay
                          checks their required inputs and saved reports before
                          starting.{" "}
                        </>
                      }
                    >
                      <MenuItem value="">Start at the beginning</MenuItem>
                      {(workflow?.entrypoints ?? []).map((entry) => (
                        <MenuItem
                          key={entry.scope_path}
                          value={entry.scope_path}
                        >
                          {stageLabel(entry.scope_path)}
                        </MenuItem>
                      ))}
                    </HelpSelectField>
                  )}
                </Stack>
              </AccordionDetails>
            </Accordion>
          </Stack>
        </DialogContent>
        <DialogActions>
          <Button onClick={onClose} disabled={launching}>
            Cancel
          </Button>
          <Button type="submit" variant="contained" disabled={reason !== null}>
            {launching ? "Starting…" : "Run workflow"}
          </Button>
        </DialogActions>
      </form>
    </Dialog>
  );
}
