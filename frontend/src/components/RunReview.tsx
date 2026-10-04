import {
  Alert, Button, Checkbox,
  FormControl, FormControlLabel, InputLabel, MenuItem, Paper, Select, Stack, TextField, Typography,
} from "@mui/material";
import { useEffect, useId, useMemo, useRef, useState } from "react";

import { api, errorMessage } from "../api";
import { stageLabel } from "../navigation";
import type { ArtifactRecord, JsonValue, RunInteraction } from "../types";

function object(value: JsonValue | undefined): Record<string, JsonValue> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value) ? value : null;
}

export function ReviewEvidence({ runId, artifacts }: { runId: string; artifacts: ArtifactRecord[] }) {
  const labelId = useId();
  const documents = useMemo(() => {
    const latest = new Map<string, ArtifactRecord>();
    for (const item of artifacts) {
      // /worktrees/<run>/r-12/docs/REVIEW.md becomes docs/REVIEW.md.
      // Keep directories so docs/REVIEW.md and audit/REVIEW.md remain distinct.
      const source = item.source_path.replace(/\\/g, "/");
      const marker = `/worktrees/${runId}/`;
      const offset = source.indexOf(marker);
      const name = offset >= 0 ? source.slice(offset + marker.length).replace(/^r-\d+\//, "") : source;
      const previous = latest.get(name);
      if (!previous || Number(item.id) > Number(previous.id)) latest.set(name, item);
    }
    return Array.from(latest, ([label, artifact]) => ({ label, artifact }));
  }, [artifacts, runId]);
  const [selection, setSelection] = useState("changes");
  const [preview, setPreview] = useState<{ text: string; truncated: boolean; previewable?: boolean } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [opened, setOpened] = useState(false);
  useEffect(() => {
    if (!opened) return;
    const controller = new AbortController();
    setPreview(null); setError(null);
    const path = selection === "changes" ? `/api/runs/${runId}/changes` : `/api/artifacts/${selection}/preview`;
    void api<{ text: string; truncated: boolean; previewable?: boolean }>(path, { signal: controller.signal })
      .then(setPreview).catch((caught: unknown) => { if (!controller.signal.aborted) setError(errorMessage(caught)); });
    return () => controller.abort();
  }, [runId, selection, opened]);
  return <Stack spacing={1.5}>
    <Typography variant="subtitle2">Review documents and code changes</Typography>
    <Typography variant="body2" color="text.secondary">Choose a retained document or the run's committed changes. Follow the review instructions before sending your response.</Typography>
    <FormControl size="small"><InputLabel id={labelId}>Review material</InputLabel><Select labelId={labelId} label="Review material" value={selection} onChange={(event) => { setSelection(event.target.value); setOpened(true); }}>
      <MenuItem value="changes">Committed code changes</MenuItem>
      {documents.map(({ artifact, label }) => <MenuItem key={artifact.id} value={artifact.id}>{label || artifact.name}</MenuItem>)}
    </Select></FormControl>
    {!opened && <Button variant="outlined" onClick={() => setOpened(true)}>Open review material</Button>}
    {error && <Alert severity="error">{error}</Alert>}
    {opened && !preview && !error && <Typography>Loading review material…</Typography>}
    {preview && <>
      {preview.previewable === false ? <Typography>This file needs to be downloaded to view it.</Typography>
        : <Typography component="pre" className="review-preview">{preview.text || "No committed code changes yet."}</Typography>}
      {preview.truncated && <Alert severity="info">{selection === "changes" ? "This preview shows the beginning of a large diff. Review the full diff on the run branch shown in Advanced diagnostics before responding." : "This preview shows the beginning of a large document. Download the complete document before reviewing it."}</Alert>}
      {selection !== "changes" && <Button component="a" href={`/api/artifacts/${selection}`} download>Download complete document</Button>}
    </>}
    {documents.length === 0 && <Typography variant="body2">No report files were retained. Read the workflow's instructions and review the committed changes.</Typography>}
  </Stack>;
}

export function ReviewRequest({ interaction, runId, artifacts, selected, onAnswered }: {
  interaction: RunInteraction; runId: string; artifacts: ArtifactRecord[]; selected: boolean;
  onAnswered: () => Promise<void>;
}) {
  const options = Array.isArray(interaction.request.options) ? interaction.request.options : [];
  const labelId = useId();
  const mode = object(object(options[0])?.mode);
  const schema = object(mode?.requestedSchema);
  const fields = object(schema?.properties);
  const required = Array.isArray(schema?.required) ? schema.required : [];
  const [value, setValue] = useState("");
  const [form, setForm] = useState<Record<string, JsonValue>>({});
  const [feedback, setFeedback] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const card = useRef<HTMLDivElement | null>(null);
  const isReview = interaction.kind === "wait";
  const simpleForm = fields !== null && Object.values(fields).every((field) => {
    const type = object(field)?.type;
    return type === "string" || type === "boolean" || type === "number" || type === "integer";
  });
  useEffect(() => { if (selected) card.current?.scrollIntoView({ block: "center", behavior: "smooth" }); }, [selected]);
  function link() {
    const url = new URL(window.location.href);
    url.searchParams.set("view", "runs"); url.searchParams.set("run", runId); url.searchParams.set("interaction", interaction.id);
    return url.toString();
  }
  async function answer(decline = false) {
    setBusy(true); setError(null);
    try {
      let answerValue: JsonValue = value;
      if (interaction.kind === "elicitation") {
        answerValue = decline ? null : simpleForm ? form : JSON.parse(value);
        if (answerValue !== null && (typeof answerValue !== "object" || Array.isArray(answerValue))) throw new Error("Enter the requested fields or decline the request.");
      }
      await api(`/api/attempts/${interaction.attempt_id}/${interaction.kind}`, {
        method: "POST", body: JSON.stringify({
          idempotency_key: crypto.randomUUID(), interaction_id: interaction.id,
          ...(interaction.kind === "permission" ? { decision: value } : { value: answerValue }),
          ...(!isReview && feedback.trim() ? { feedback } : {}),
        }),
      });
      await onAnswered();
    } catch (caught) { setError(errorMessage(caught)); } finally { setBusy(false); }
  }
  const ready = interaction.kind === "elicitation" && simpleForm
    ? required.every((name) => typeof name === "string" && form[name] !== undefined && form[name] !== "") : value !== "";
  return <Paper ref={card} id={`request-${interaction.id}`} variant="outlined" className="interaction-card" sx={{ borderColor: selected ? "primary.main" : "warning.main" }}>
    <Stack spacing={2}>
      <Stack direction="row" spacing={1} sx={{ alignItems: "center", justifyContent: "space-between" }}>
        <Typography variant="h6">{isReview ? "Your review is needed" : interaction.kind === "permission" ? "A tool needs your permission" : "An agent needs an answer"}</Typography>
        <Button component="a" href={link()}>Link to request</Button>
      </Stack>
      <Typography variant="subtitle2">{stageLabel(interaction.scope_path)}</Typography>
      <Typography sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{String(interaction.request.prompt ?? "Owner input required.")}</Typography>
      {interaction.deadline && <Typography variant="body2">Respond before {new Date(interaction.deadline).toLocaleString()}.</Typography>}
      {isReview && <ReviewEvidence runId={runId} artifacts={artifacts} />}
      {interaction.kind === "permission" ? <FormControl size="small"><InputLabel id={labelId}>Your decision</InputLabel><Select labelId={labelId} label="Your decision" value={value} onChange={(event) => setValue(event.target.value)}>
        {options.flatMap((item) => {
          const option = object(item); const id = typeof item === "string" ? item : option?.id;
          return typeof id === "string" ? [<MenuItem key={id} value={id}>{String(option?.name ?? id)}</MenuItem>] : [];
        })}
      </Select></FormControl> : interaction.kind === "elicitation" && simpleForm ? <Stack spacing={1.5}>
        {Object.entries(fields ?? {}).map(([name, raw]) => {
          const field = object(raw) ?? {}; const label = String(field.title ?? stageLabel(name));
          return field.type === "boolean" ? <FormControlLabel key={name} label={label} control={<Checkbox checked={form[name] === true} onChange={(event) => setForm((current) => ({ ...current, [name]: event.target.checked }))} />} />
           : Array.isArray(field.enum) ? <FormControl key={name}><InputLabel id={`${labelId}-${name}`}>{label}</InputLabel><Select labelId={`${labelId}-${name}`} label={label} value={String(form[name] ?? "")} onChange={(event) => setForm((current) => ({ ...current, [name]: (Array.isArray(field.enum) ? field.enum.find((item) => String(item) === event.target.value) : undefined) ?? event.target.value }))}>
            {field.enum.map((item) => <MenuItem key={String(item)} value={String(item)}>{String(item)}</MenuItem>)}
          </Select></FormControl> : <TextField key={name} label={label} required={required.includes(name)} helperText={typeof field.description === "string" ? field.description : undefined} value={form[name] ?? ""} type={field.type === "number" || field.type === "integer" ? "number" : "text"} onChange={(event) => setForm((current) => ({ ...current, [name]: field.type === "number" || field.type === "integer" ? (event.target.value === "" ? "" : Number(event.target.value)) : event.target.value }))} />;
        })}
      </Stack> : <TextField label={isReview ? "Your response" : "Response (JSON object)"} value={value} onChange={(event) => setValue(event.target.value)} multiline minRows={2} helperText={isReview ? "Use the response requested in the instructions above. Sending it allows the next steps to continue." : "Enter the fields requested by the agent, or decline below."} />}
      {!isReview && <TextField label="Feedback for the agent (optional)" value={feedback} onChange={(event) => setFeedback(event.target.value)} multiline minRows={2} helperText="Your decision answers this request. Feedback is sent in the same session after the agent finishes this turn; it does not grant permission." />}
      <Typography variant="body2" color="text.secondary">{isReview ? "This is a human review. Relay will not approve it for you." : "Select a response deliberately. Relay resumes the agent with your answer."}</Typography>
      {error && <Alert severity="error">{error}</Alert>}
      <Stack direction="row" spacing={1}><Button variant="contained" onClick={() => void answer()} disabled={busy || !ready}>{busy ? "Sending…" : "Send response and continue"}</Button>
        {interaction.kind === "elicitation" && <Button disabled={busy} onClick={() => void answer(true)}>Decline request</Button>}
      </Stack>
    </Stack>
  </Paper>;
}
