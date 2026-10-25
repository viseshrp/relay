import { Alert, Button, MenuItem, Stack, TextField } from "@mui/material";
import { useState } from "react";

import { api, errorMessage } from "../api";
import { projectPath } from "../navigation";
import type { WorkflowNote } from "../types";

export function notesPath(workflowKey: string, suffix = ""): string {
  return `/api/workflows/${workflowKey.split("/").map(encodeURIComponent).join("/")}/notes${suffix}`;
}

/** Cue, lesson, and evidence are all required, so every note says why it exists. */
export function WorkflowNoteForm({
  workflowKey,
  project,
  evidenceRunId = null,
  initialEvidence = "",
  onSaved,
  onCancel,
}: {
  workflowKey: string;
  project: string | null;
  evidenceRunId?: string | null;
  initialEvidence?: string;
  onSaved: (note: WorkflowNote) => void;
  onCancel?: () => void;
}) {
  const [cue, setCue] = useState("");
  const [lesson, setLesson] = useState("");
  const [evidence, setEvidence] = useState(initialEvidence);
  const [confidence, setConfidence] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const ready = cue.trim() && lesson.trim() && evidence.trim();
  async function save(): Promise<void> {
    setSaving(true);
    setError(null);
    try {
      const response = await api<{ note: WorkflowNote }>(
        projectPath(notesPath(workflowKey), project),
        {
          method: "POST",
          body: JSON.stringify({
            cue,
            lesson,
            evidence,
            ...(confidence ? { confidence } : {}),
            ...(evidenceRunId ? { evidence_run_id: evidenceRunId } : {}),
          }),
        },
      );
      setCue("");
      setLesson("");
      setEvidence("");
      setConfidence("");
      onSaved(response.note);
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setSaving(false);
    }
  }
  return (
    <Stack spacing={2} component="form" aria-label="New workflow note">
      <TextField
        required
        label="When does this apply?"
        helperText="The situation, for example: the full test suite times out."
        value={cue}
        onChange={(event) => setCue(event.target.value)}
        slotProps={{ htmlInput: { maxLength: 500 } }}
      />
      <TextField
        required
        multiline
        minRows={2}
        label="What should the agent do?"
        value={lesson}
        onChange={(event) => setLesson(event.target.value)}
        slotProps={{ htmlInput: { maxLength: 4000 } }}
      />
      <TextField
        required
        multiline
        minRows={2}
        label="What showed this?"
        helperText="Name the run and what happened, so the note can be checked later."
        value={evidence}
        onChange={(event) => setEvidence(event.target.value)}
        slotProps={{ htmlInput: { maxLength: 2000 } }}
      />
      <TextField
        select
        label="Confidence"
        value={confidence}
        onChange={(event) => setConfidence(event.target.value)}
      >
        <MenuItem value="">Not stated</MenuItem>
        <MenuItem value="low">Low</MenuItem>
        <MenuItem value="medium">Medium</MenuItem>
        <MenuItem value="high">High</MenuItem>
      </TextField>
      {error && <Alert severity="error">{error}</Alert>}
      <Stack direction="row" spacing={1}>
        <Button
          variant="contained"
          disabled={!ready || saving}
          onClick={() => void save()}
        >
          Save note
        </Button>
        {onCancel && <Button onClick={onCancel}>Cancel</Button>}
      </Stack>
    </Stack>
  );
}
