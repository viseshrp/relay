import { ViewSkeleton } from "./ViewSkeleton";
import { WorkflowEditorHeader } from "./WorkflowEditorHeader";
import { WorkflowEditorDialogs } from "./WorkflowEditorDialogs";
import { WorkflowCanvas } from "./WorkflowCanvas";
import {
  Alert,
  Box,
  Button,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";

import { errorMessage } from "../api";

import { WorkflowSettings } from "./WorkflowSettings";

import { WorkflowSourceSettings } from "./WorkflowSourceSettings";

import { formatWorkflowYaml } from "../source-format";

import { WorkflowSidebar } from "./WorkflowSidebar";

import type { ActionsWorkflowWorkspaceState } from "./useActionsWorkflowWorkspace";
export function ActionsWorkflowWorkspaceView({
  state,
}: {
  state: ActionsWorkflowWorkspaceState;
}) {
  const {
    inventory,
    setLoadRevision,
    key,
    props,
    setCreate,
    flush,
    setKey,
    setError,
    parsed,
    disabled,
    lease,
    valid,
    text,
    saved,
    promptEdits,
    setSourceSettings,
    sourceSettings,
    manifest,
    change,
    mode,
    setMode,
    canUndo,
    undo,
    canRedo,
    redo,
    setFormatted,
    restoreSaved,
    setSettings,
    settings,
    setEnvironments,
    notice,
    leaseError,
    takeOver,
    error,
    draft,
    diagnostics,
    setJobId,
    setDrawer,
  } = state;
  if ((!state.loadedDocument || !manifest) && !error)
    return <ViewSkeleton view="workflows" header={false} />;
  return (
    <Box className="actions-layout">
      <WorkflowSidebar
        workflows={inventory}
        selected={key}
        project={props.project.id}
        editor
        onCreate={() => setCreate(true)}
        onSelect={(next) => {
          if (!next) {
            window.location.assign(
              `/?view=runs&project=${encodeURIComponent(props.project.id)}`,
            );
            return;
          }
          void flush()
            .then(() => setKey(next))
            .catch((e) => setError(errorMessage(e)));
        }}
      />
      <Stack spacing={2} className="actions-main">
        <WorkflowEditorHeader state={state} />
        {disabled && (
          <Alert severity="info">
            This workflow is disabled. Enable it to run again.
          </Alert>
        )}
        <Button
          disabled={!parsed.value}
          onClick={() => setSourceSettings(true)}
        >
          Workflow settings
        </Button>
        <WorkflowSourceSettings
          open={sourceSettings}
          value={parsed.value}
          manifest={manifest}
          change={change}
          onClose={() => setSourceSettings(false)}
        />
        <TextField
          select
          label="Editor mode"
          value={mode}
          onChange={(event) => setMode(event.target.value)}
        >
          {["Visual", "YAML", "Split"].map((item) => (
            <MenuItem value={item} key={item}>
              {item}
            </MenuItem>
          ))}
        </TextField>
        <Stack direction="row" spacing={1}>
          <Button disabled={!canUndo} onClick={undo}>
            Undo
          </Button>
          <Button disabled={!canRedo} onClick={redo}>
            Redo
          </Button>
          <Button
            disabled={!parsed.value}
            onClick={() => {
              try {
                setFormatted(formatWorkflowYaml(text));
              } catch (e) {
                setError(errorMessage(e));
              }
            }}
          >
            Format as YAML
          </Button>
        </Stack>
        {(text !== saved || Object.keys(promptEdits).length > 0) && (
          <Alert
            severity="info"
            action={
              <Button onClick={() => void restoreSaved()}>
                Discard changes
              </Button>
            }
          >
            Unsaved changes:{" "}
            {[text !== saved ? key : "", ...Object.keys(promptEdits)]
              .filter(Boolean)
              .join(", ")}
          </Alert>
        )}
        <Button onClick={() => setSettings(true)}>
          Variables, secrets, environments and library
        </Button>
        <WorkflowSettings
          open={settings}
          projectId={props.requestProject || props.project.id}
          yaml={text}
          onClose={() => setSettings(false)}
          onEnvironments={setEnvironments}
        />
        <Typography>
          {lease && valid
            ? "Ready to edit"
            : lease
              ? "Validating workflow…"
              : "Connecting editor…"}
        </Typography>
        {notice && <Alert severity="success">{notice}</Alert>}
        {!key && <Typography variant="h6">No workflows yet</Typography>}
        {leaseError && (
          <Alert
            severity="info"
            action={
              <Button onClick={() => void takeOver()}>Edit here instead</Button>
            }
          >
            {leaseError}
          </Alert>
        )}
        {error && (
          <Alert severity="error">
            {error}
            {!text && (
              <Button onClick={() => setLoadRevision((value) => value + 1)}>
                Retry workflow
              </Button>
            )}
          </Alert>
        )}
        {(draft || text !== saved) && saved && (
          <Alert severity="info">
            Your unsaved draft is not included when you run the saved workflow.
            <Button onClick={() => void restoreSaved()}>
              Restore saved source
            </Button>
            <Box component="details">
              <Box component="summary">Compare draft with saved source</Box>
              <Typography
                component="pre"
                sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}
              >
                Saved source:{"\n"}
                {saved}
                {"\n"}Draft:{"\n"}
                {text}
              </Typography>
            </Box>
          </Alert>
        )}
        {diagnostics.map((item, i) => (
          <Alert
            severity="error"
            key={i}
            action={
              item.context?.field?.match(/^jobs\.([^.[]+)/) ? (
                <Button
                  onClick={() => {
                    setJobId(item.context!.field!.match(/^jobs\.([^.[]+)/)![1]);
                    setDrawer(true);
                  }}
                >
                  Open job
                </Button>
              ) : undefined
            }
          >
            {item.context?.line ? `Line ${item.context.line}: ` : ""}
            {item.message}
          </Alert>
        ))}
        {key && !text && !error ? (
          <ViewSkeleton view="workflows" header={false} />
        ) : (
          <WorkflowCanvas state={state} />
        )}
        <WorkflowEditorDialogs state={state} />
      </Stack>
    </Box>
  );
}
