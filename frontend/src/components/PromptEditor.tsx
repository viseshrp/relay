import { Alert, Button, Stack, TextField, Typography } from "@mui/material";
import { useEffect, useState } from "react";

import { api, errorMessage } from "../api";
import { projectPath } from "../navigation";

interface PromptDocument { text: string; reference: string; base_hash: string }

export function PromptEditor({ workflowPath, reference, newReference, project, holder, disabled, onSaved, onDirty }: {
  workflowPath: string; reference: string | null; newReference: string;
  project: string | null; holder: string; disabled: boolean;
  onSaved: (reference: string) => void;
  onDirty: (dirty: boolean) => void;
}) {
  const [text, setText] = useState("");
  const [saved, setSaved] = useState<PromptDocument | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { onDirty(text !== (saved?.text ?? "")); }, [text, saved, onDirty]);
  useEffect(() => () => onDirty(false), [onDirty]);
  useEffect(() => {
    const controller = new AbortController();
    setSaved(null); setText(""); setError(null);
    if (reference) {
      setBusy(true);
      const path = projectPath(`${workflowPath}/prompt?reference=${encodeURIComponent(reference)}`, project);
      void api<PromptDocument>(path, { signal: controller.signal }).then((value) => {
        setSaved(value); setText(value.text);
      }).catch((caught: unknown) => {
        if (!controller.signal.aborted) setError(errorMessage(caught));
      }).finally(() => { if (!controller.signal.aborted) setBusy(false); });
    }
    return () => controller.abort();
  }, [workflowPath, reference, project]);

  async function save() {
    setBusy(true); setError(null);
    try {
      const value = await api<PromptDocument>(projectPath(`${workflowPath}/prompt`, project), {
        method: "POST", body: JSON.stringify({ holder, reference: reference ?? newReference, text, base_hash: saved?.base_hash ?? null }),
      });
      setSaved(value); onSaved(value.reference);
    } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(false); }
  }
  return <Stack spacing={1.5}>
    <Typography variant="subtitle2">Instructions for this agent</Typography>
    <TextField label="What should the agent do?" multiline minRows={5} value={text} disabled={busy || disabled}
      onChange={(event) => setText(event.target.value)} helperText="Describe the result you want and any limits. These instructions belong to the selected project." />
    {error && <Alert severity="error">{error}</Alert>}
    <Button variant="outlined" disabled={busy || disabled || !text.trim() || text === saved?.text || (reference !== null && saved === null)} onClick={() => void save()}>Save instructions</Button>
    {saved && text === saved.text && <Typography variant="caption" color="text.secondary">Instructions saved. Save the workflow to include them in the next run.</Typography>}
  </Stack>;
}
