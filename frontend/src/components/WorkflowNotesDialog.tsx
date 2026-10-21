import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  Typography,
} from "@mui/material";
import { useState } from "react";

import { api, errorMessage } from "../api";
import { projectPath } from "../navigation";
import type { WorkflowNote } from "../types";
import { useResource } from "../useResource";
import { WorkflowNoteForm, notesPath } from "./WorkflowNoteForm";

export function NoteSummary({ note }: { note: WorkflowNote }) {
  return (
    <Box>
      <Typography variant="subtitle2">When: {note.cue}</Typography>
      <Typography variant="body2">Do: {note.lesson}</Typography>
      <Typography variant="body2" color="text.secondary">
        Because: {note.evidence}
        {note.confidence ? ` · Confidence: ${note.confidence}` : ""}
      </Typography>
    </Box>
  );
}

/** Review, add, and archive the lessons a workflow can carry into later runs. */
export function WorkflowNotesDialog({
  open,
  workflowKey,
  project,
  onClose,
}: {
  open: boolean;
  workflowKey: string;
  project: string | null;
  onClose: () => void;
}) {
  const { data, error, reload } = useResource<{ notes: WorkflowNote[] }>(
    open ? projectPath(notesPath(workflowKey), project) : null,
  );
  const [archiveError, setArchiveError] = useState<string | null>(null);
  const [adding, setAdding] = useState(false);
  async function archive(note: WorkflowNote): Promise<void> {
    setArchiveError(null);
    try {
      await api(
        projectPath(notesPath(workflowKey, `/${note.id}/archive`), project),
        {
          method: "POST",
          body: "{}",
        },
      );
      reload();
    } catch (caught) {
      setArchiveError(errorMessage(caught));
    }
  }
  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="md">
      <DialogTitle>Workflow notes</DialogTitle>
      <DialogContent>
        <Stack spacing={2}>
          <Typography variant="body2">
            Notes are lessons you approve from earlier runs. Choose them when
            you start a run; Relay gives each agent step the chosen notes as a
            separate block after its prompt files. Starting a run never changes
            or adds notes.
          </Typography>
          {error && <Alert severity="error">{error}</Alert>}
          {archiveError && <Alert severity="error">{archiveError}</Alert>}
          {data?.notes.length === 0 && (
            <Typography color="text.secondary">No notes yet.</Typography>
          )}
          {data?.notes.map((note) => (
            <Stack
              key={note.id}
              direction="row"
              spacing={2}
              sx={{ alignItems: "flex-start" }}
            >
              <Box sx={{ flex: 1 }}>
                <NoteSummary note={note} />
              </Box>
              <Button
                aria-label={`Archive note: ${note.cue}`}
                onClick={() => void archive(note)}
              >
                Archive
              </Button>
            </Stack>
          ))}
          {adding ? (
            <WorkflowNoteForm
              workflowKey={workflowKey}
              project={project}
              onSaved={() => {
                setAdding(false);
                reload();
              }}
              onCancel={() => setAdding(false)}
            />
          ) : (
            <Box>
              <Button variant="outlined" onClick={() => setAdding(true)}>
                Add note
              </Button>
            </Box>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
