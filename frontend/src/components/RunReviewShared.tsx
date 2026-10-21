import {
  Alert,
  Button,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Typography,
} from "@mui/material";
import { useEffect, useId, useMemo, useRef, useState } from "react";
import { api, errorMessage } from "../api";

import {
  artifactPath,
  defaultReviewSelection,
  visibleArtifacts,
} from "../artifacts";

import type { ArtifactRecord, JsonValue } from "../types";
import { DiffViewer } from "./DiffViewer";
type ReadResponse1 = {
  text: string;
  truncated: boolean;
  previewable?: boolean;
};

function object(
  value: JsonValue | undefined,
): Record<string, JsonValue> | null {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value
    : null;
}

type ElicitationChoice = {
  value: string | number | boolean;
  label: string;
  description?: string;
};

function scalarChoice(
  value: JsonValue | undefined,
): value is string | number | boolean {
  return ["string", "number", "boolean"].includes(typeof value);
}

export function elicitationChoices(
  field: Record<string, JsonValue>,
): ElicitationChoice[] | null {
  const values = field.enum;
  if (Array.isArray(values)) {
    if (field.oneOf != null || !values.length || !values.every(scalarChoice))
      return null;
    return values.map((value) => ({ value, label: String(value) }));
  }
  if (!Array.isArray(field.oneOf) || !field.oneOf.length) return null;
  const choices: ElicitationChoice[] = [];
  for (const raw of field.oneOf) {
    const option = object(raw);
    if (!option || typeof option.const !== "string") return null;
    choices.push({
      value: option.const,
      label: typeof option.title === "string" ? option.title : option.const,
      ...(typeof option.description === "string"
        ? { description: option.description }
        : {}),
    });
  }
  return choices;
}

export function ReviewEvidence({
  runId,
  artifacts,
  hasChanges,
  onLoadAll,
  pendingReview = false,
  requestText = null,
}: {
  runId: string;
  artifacts: ArtifactRecord[];
  /** Whether the run committed code, from the run record, not a loaded page. */
  hasChanges: boolean;
  /** Load the remaining artifact pages before the owner chooses one. */
  onLoadAll?: () => Promise<void>;
  pendingReview?: boolean;
  /** A pending review's instructions; a document they name is shown first. */
  requestText?: string | null;
}) {
  const labelId = useId();
  const documents = useMemo(() => {
    const latest = new Map<string, ArtifactRecord>();
    for (const item of visibleArtifacts(artifacts).filter(
      (item) => !["commits", "commits.json"].includes(item.name),
    )) {
      const name = artifactPath(runId, item);
      const previous = latest.get(name);
      if (!previous || Number(item.id) > Number(previous.id))
        latest.set(name, item);
    }
    return Array.from(latest, ([label, artifact]) => ({ label, artifact }));
  }, [artifacts, runId]);
  const loadedAll = useRef(false);
  const [chosen, setSelection] = useState<string | null>(null);
  const selection =
    chosen &&
    (chosen === "changes"
      ? hasChanges
      : documents.some((item) => item.artifact.id === chosen))
      ? chosen
      : defaultReviewSelection(
          documents,
          hasChanges,
          pendingReview ? requestText : null,
        );
  const [preview, setPreview] = useState<{
    text: string;
    truncated: boolean;
    previewable?: boolean;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [opened, setOpened] = useState(false);
  useEffect(() => {
    if (!opened || !selection) return;
    const controller = new AbortController();
    setPreview(null);
    setError(null);
    const path =
      selection === "changes"
        ? `/api/runs/${runId}/changes`
        : `/api/artifacts/${selection}/preview`;
    void api<ReadResponse1>(path, { signal: controller.signal })
      .then(setPreview)
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) setError(errorMessage(caught));
      });
    return () => controller.abort();
  }, [runId, selection, opened]);
  if (!hasChanges && !documents.length) return null;
  return (
    <Stack spacing={1.5}>
      <Typography variant="subtitle2">
        {pendingReview
          ? "Review documents and code changes"
          : "Changes and documents"}
      </Typography>
      <Typography variant="body2" color="text.secondary">
        Choose a retained document or the run's committed changes.
        {pendingReview
          ? " Follow the review instructions before sending your response."
          : ""}
      </Typography>
      <FormControl size="small">
        <InputLabel id={labelId}>Review material</InputLabel>
        <Select
          labelId={labelId}
          label="Review material"
          value={selection ?? ""}
          onOpen={() => {
            if (loadedAll.current || !onLoadAll) return;
            loadedAll.current = true;
            void onLoadAll();
          }}
          onChange={(event) => {
            setSelection(event.target.value);
            setOpened(true);
          }}
        >
          {hasChanges && (
            <MenuItem value="changes">Committed code changes</MenuItem>
          )}
          {documents.map(({ artifact, label }) => (
            <MenuItem key={artifact.id} value={artifact.id}>
              {label || artifact.name}
            </MenuItem>
          ))}
        </Select>
      </FormControl>
      {!opened && (
        <Button variant="outlined" onClick={() => setOpened(true)}>
          {pendingReview
            ? "Open review material"
            : "Open changes and documents"}
        </Button>
      )}
      {error && <Alert severity="error">{error}</Alert>}
      {opened && !preview && !error && (
        <Typography>Loading review material…</Typography>
      )}
      {preview && (
        <>
          {selection === "changes" ? (
            <DiffViewer
              key={runId}
              text={preview.text}
              truncated={preview.truncated}
            />
          ) : preview.previewable === false ? (
            <Typography>
              This file needs to be downloaded to view it.
            </Typography>
          ) : (
            <Typography component="pre" className="review-preview">
              {preview.text || "No committed code changes yet."}
            </Typography>
          )}
          {preview.truncated && selection !== "changes" && (
            <Alert severity="info">
              This preview shows the beginning of a large document. Download the
              complete document before reviewing it.
            </Alert>
          )}
          {selection !== "changes" && (
            <Button component="a" href={`/api/artifacts/${selection}`} download>
              Download complete document
            </Button>
          )}
        </>
      )}
      {documents.length === 0 && (
        <Typography variant="body2">
          No report files were retained. Read the workflow's instructions and
          review the committed changes.
        </Typography>
      )}
    </Stack>
  );
}
export { object };
