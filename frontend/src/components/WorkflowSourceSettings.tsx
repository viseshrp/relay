import {
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import type { ActionWorkflow } from "../actions-workflow";
import type { LanguageManifest } from "../workflow-language";
import { isRecord } from "../workflow";
import { SchemaFields } from "./SchemaFields";
import { WorkflowInputsEditor } from "./WorkflowInputsEditor";

export function WorkflowSourceSettings({
  open,
  value,
  manifest,
  change,
  onClose,
}: {
  open: boolean;
  value: ActionWorkflow | null;
  manifest: LanguageManifest | null;
  change: (path: Array<string | number>, value: unknown) => void;
  onClose: () => void;
}) {
  const events = isRecord(value?.on)
    ? value.on
    : typeof value?.on === "string"
      ? { [value.on]: {} }
      : {};
  const dispatch = isRecord(events.workflow_dispatch)
    ? events.workflow_dispatch
    : {};
  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="md">
      <DialogTitle>Workflow settings</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 2 }}>
          <TextField
            label="Workflow name"
            margin="dense"
            slotProps={{ htmlInput: { maxLength: 256 } }}
            value={value?.name ?? ""}
            onChange={(event) => change(["name"], event.target.value)}
          />
          <TextField
            label="Run title expression"
            margin="dense"
            slotProps={{ htmlInput: { maxLength: 1000 } }}
            value={value?.["run-name"] ?? ""}
            onChange={(event) =>
              change(["run-name"], event.target.value || undefined)
            }
          />
          <Typography component="h2" variant="h6">
            Launch inputs
          </Typography>
          <WorkflowInputsEditor
            value={dispatch.inputs}
            onChange={(inputs) =>
              change(["on"], {
                ...events,
                workflow_dispatch: { ...dispatch, inputs },
              })
            }
          />
          {manifest && (
            <Box component="details" sx={{ mt: 1 }}>
              <Box component="summary" sx={{ cursor: "pointer", mb: 1 }}>
                <Typography
                  variant="body2"
                  color="text.secondary"
                  component="span"
                >
                  Advanced workflow schema fields
                </Typography>
              </Box>
              <SchemaFields
                manifest={manifest}
                type="workflow-root"
                value={value}
                omit={["jobs", "name", "run-name", "on"]}
                onChange={(field, entry) => change([field], entry)}
              />
            </Box>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Done</Button>
      </DialogActions>
    </Dialog>
  );
}
