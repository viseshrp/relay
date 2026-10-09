import {
  Alert,
  Button,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import { projectPath } from "../navigation";
import { MarkdownEditor } from "./MarkdownEditor";
type ReadResponse1 = { prompts: Array<{ reference: string }> };
type ReadResponse2 = { reference: string; text: string; base_hash: string };

export type PromptEdits = Record<
  string,
  { text: string; base_hash: string | null }
>;
export function PromptFilesEditor({
  references,
  workflowKey,
  project,
  job,
  edits,
  onEdits,
  onReferences,
}: {
  references: string;
  workflowKey: string;
  project: string | null;
  job: string;
  edits: PromptEdits;
  onEdits: (reference: string, edit: PromptEdits[string]) => void;
  onReferences: (value: string) => void;
}) {
  const refs = references
    .split(/\r?\n/)
    .map((value) => value.trim())
    .filter(Boolean);
  const [inventory, setInventory] = useState<string[]>([]);
  const [selection, setSelection] = useState("");
  const [newName, setNewName] = useState(`${job}-instructions.md`);
  const [existing, setExisting] = useState("");
  const [loaded, setLoaded] = useState<{
    reference: string;
    text: string;
    base_hash: string;
  } | null>(null);
  const [error, setError] = useState("");
  const [dragged, setDragged] = useState(-1);
  const selected = refs.includes(selection) ? selection : (refs[0] ?? "");
  useEffect(() => {
    const controller = new AbortController();
    void api<ReadResponse1>(projectPath("/api/workflow-prompts", project), {
      signal: controller.signal,
    })
      .then((result) =>
        setInventory(result.prompts.map((item) => item.reference)),
      )
      .catch((caught) => {
        if (!controller.signal.aborted) setError(errorMessage(caught));
      });
    return () => controller.abort();
  }, [project]);
  const hasSelectedEdit = Boolean(edits[selected]);
  useEffect(() => {
    setLoaded(null);
    setError("");
    if (!selected || hasSelectedEdit) return;
    const controller = new AbortController();
    void api<ReadResponse2>(
      projectPath(
        `/api/workflows/${workflowKey.split("/").map(encodeURIComponent).join("/")}/prompt?reference=${encodeURIComponent(selected)}`,
        project,
      ),
      { signal: controller.signal },
    )
      .then((value) => {
        if (!controller.signal.aborted) setLoaded(value);
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(errorMessage(caught));
      });
    return () => controller.abort();
  }, [selected, workflowKey, project, hasSelectedEdit]);
  function reorder(from: number, to: number) {
    const next = [...refs];
    const [item] = next.splice(from, 1);
    next.splice(to, 0, item);
    onReferences(next.join("\n"));
  }
  const document =
    edits[selected] ?? (loaded?.reference === selected ? loaded : null);
  return (
    <Stack spacing={1.5}>
      <Typography component="h3" variant="subtitle1">
        Ordered prompt files
      </Typography>
      <Stack component="ol" spacing={1} sx={{ p: 0, listStyle: "none" }}>
        {refs.map((reference, index) => (
          <Stack
            key={`${reference}-${index}`}
            component="li"
            draggable
            onDragStart={() => setDragged(index)}
            onDragOver={(event) => event.preventDefault()}
            onDrop={() => {
              if (dragged >= 0) reorder(dragged, index);
              setDragged(-1);
            }}
            direction="row"
            spacing={1}
            sx={{ flexWrap: "wrap" }}
          >
            <Button
              sx={{ overflowWrap: "anywhere", minWidth: 0 }}
              aria-pressed={selected === reference}
              onClick={() => setSelection(reference)}
            >
              {index + 1}.{" "}
              {reference.startsWith("global:")
                ? reference
                : `.relay/${reference}`}
            </Button>
            <Button
              disabled={index === 0}
              aria-label={`Move prompt ${index + 1} earlier`}
              onClick={() => reorder(index, index - 1)}
            >
              ↑
            </Button>
            <Button
              disabled={index === refs.length - 1}
              aria-label={`Move prompt ${index + 1} later`}
              onClick={() => reorder(index, index + 1)}
            >
              ↓
            </Button>
            <Button
              aria-label={`Remove prompt ${index + 1}`}
              onClick={() =>
                onReferences(
                  refs.filter((_, offset) => offset !== index).join("\n"),
                )
              }
            >
              Remove
            </Button>
          </Stack>
        ))}
      </Stack>
      <Stack direction="row" spacing={1}>
        <TextField
          label="New prompt file"
          value={newName}
          onChange={(event) => setNewName(event.target.value)}
        />
        <Button
          disabled={!newName.trim()}
          onClick={() => {
            const name = newName.startsWith("prompts/")
              ? newName
              : `prompts/${newName}`;
            if (inventory.includes(name) || edits[name]) {
              setError("Use the existing prompt instead of replacing it.");
              return;
            }
            onEdits(name, { text: "", base_hash: null });
            onReferences([...refs, name].join("\n"));
            setSelection(name);
          }}
        >
          Create prompt
        </Button>
      </Stack>
      <Stack direction="row" spacing={1}>
        <TextField
          select
          label="Use an existing prompt"
          value={existing}
          onChange={(event) => setExisting(event.target.value)}
          sx={{ flex: 1 }}
        >
          {[...new Set([...inventory, ...Object.keys(edits)])].map(
            (reference) => (
              <MenuItem key={reference} value={reference}>
                {reference}
              </MenuItem>
            ),
          )}
        </TextField>
        <Button
          disabled={!existing}
          onClick={() => {
            onReferences([...refs, existing].join("\n"));
            setSelection(existing);
          }}
        >
          Use prompt
        </Button>
      </Stack>
      {selected && (
        <Typography sx={{ overflowWrap: "anywhere" }}>
          {selected.startsWith("global:")
            ? `${selected} · Shared global prompt (read only)`
            : `.relay/${selected}`}
        </Typography>
      )}
      {document && (
        <MarkdownEditor
          label="Prompt instructions"
          value={document.text}
          readonly={selected.startsWith("global:")}
          onChange={(text) =>
            onEdits(selected, { text, base_hash: document.base_hash })
          }
        />
      )}
      {selected && !selected.startsWith("global:") && document && (
        <Button
          onClick={() => {
            const name = newName.startsWith("prompts/")
              ? newName
              : `prompts/${newName}`;
            if (
              !name ||
              name === selected ||
              inventory.includes(name) ||
              edits[name]
            ) {
              setError("Choose an unused prompt file name.");
              return;
            }
            onEdits(name, { text: document.text, base_hash: null });
            onReferences(
              refs
                .map((reference) => (reference === selected ? name : reference))
                .join("\n"),
            );
            setSelection(name);
          }}
        >
          Rename prompt
        </Button>
      )}
      <Typography variant="body2" color="text.secondary">
        Save publishes these edits with the workflow. Renaming copies this job’s
        prompt so other workflows keep their original instructions.
      </Typography>
      {error && <Alert severity="error">{error}</Alert>}
    </Stack>
  );
}
