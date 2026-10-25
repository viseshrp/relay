import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Checkbox,
  FormControlLabel,
  Stack,
  Typography,
} from "@mui/material";

import { projectPath } from "../navigation";
import type { WorkflowNote } from "../types";
import { useResource } from "../useResource";
import { ActionIcon } from "./ActionIcon";
import { notesPath } from "./WorkflowNoteForm";
import { NoteSummary } from "./WorkflowNotesDialog";

const LIMIT = 10;

/** Choose which approved notes this run's agent steps receive, in list order. */
export function LaunchNotes({
  workflowKey,
  project,
  selected,
  onSelected,
}: {
  workflowKey: string;
  project: string | null;
  selected: string[];
  onSelected: (ids: string[]) => void;
}) {
  const { data, error } = useResource<{ notes: WorkflowNote[] }>(
    projectPath(notesPath(workflowKey), project),
  );
  const notes = data?.notes ?? [];
  if (!error && !notes.length) return null;
  return (
    <Accordion>
      <AccordionSummary expandIcon={<ActionIcon name="down" />}>
        Workflow notes ({selected.length} of {notes.length} chosen)
      </AccordionSummary>
      <AccordionDetails>
        <Stack spacing={1}>
          {error && <Alert severity="error">{error}</Alert>}
          <Typography variant="body2">
            Chosen notes are captured with this run, so later edits do not
            change it. Choose up to {LIMIT}.
          </Typography>
          {notes.map((note) => (
            <FormControlLabel
              key={note.id}
              control={
                <Checkbox
                  checked={selected.includes(note.id)}
                  disabled={
                    !selected.includes(note.id) && selected.length >= LIMIT
                  }
                  onChange={(event) =>
                    onSelected(
                      notes
                        .map((item) => item.id)
                        .filter((id) =>
                          id === note.id
                            ? event.target.checked
                            : selected.includes(id),
                        ),
                    )
                  }
                />
              }
              label={<NoteSummary note={note} />}
            />
          ))}
        </Stack>
      </AccordionDetails>
    </Accordion>
  );
}
