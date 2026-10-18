import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useEffect, useState } from "react";

import { api, errorMessage } from "../api";
import { projectPath } from "../navigation";
import type { WorkflowTemplate } from "../types";
type ReadResponse1 = { templates: WorkflowTemplate[] };
type ReadResponse2 = { key: string };

/** Show the YAML word for an input type, not the compiled schema name. */
function inputTypeLabel(type: string): string {
  return type === "enum" ? "choice" : type;
}

function templateSize(template: WorkflowTemplate): string {
  const jobs = `${template.job_count} ${template.job_count === 1 ? "job" : "jobs"}`;
  if (!template.approval_count) return jobs;
  const approvals = `${template.approval_count} ${
    template.approval_count === 1 ? "approval" : "approvals"
  }`;
  return `${jobs} · ${approvals}`;
}

interface CreateWorkflowDialogProps {
  open: boolean;
  requestProject: string | null;
  holder: string;
  startBlank?: boolean;
  onClose: () => void;
  onCreated: (key: string, template: WorkflowTemplate | null) => Promise<void>;
}

export function CreateWorkflowDialog({
  open,
  requestProject,
  holder,
  startBlank = false,
  onClose,
  onCreated,
}: CreateWorkflowDialogProps) {
  const [templates, setTemplates] = useState<WorkflowTemplate[]>([]);
  const [selected, setSelected] = useState<WorkflowTemplate | null>(null);
  const [name, setName] = useState("New workflow");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(false);
  const [check, setCheck] = useState(0);

  useEffect(() => {
    if (open) {
      setSelected(null);
      setName("New workflow");
    }
  }, [open]);

  useEffect(() => {
    if (!open) return;
    let active = true;
    setLoading(true);
    setError(null);
    void api<ReadResponse1>("/api/workflow-templates")
      .then((value) => {
        if (!active) return;
        setTemplates(value.templates);
        const starter = startBlank
          ? null
          : (value.templates.find((item) => item.default) ?? null);
        setSelected(starter);
        setName(starter?.name ?? "New workflow");
      })
      .catch((caught: unknown) => {
        if (active) setError(errorMessage(caught));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [open, check, startBlank]);

  async function create() {
    setBusy(true);
    setError(null);
    try {
      const slug =
        name
          .trim()
          .toLowerCase()
          .replace(/[^a-z0-9]+/g, "-")
          .replace(/^-+|-+$/g, "") || "workflow";
      const portable = /^(con|prn|aux|nul|com[1-9]|lpt[1-9])$/i.test(slug)
        ? `workflow-${slug}`
        : slug;
      const key = selected
        ? `${portable}-${crypto.randomUUID().slice(0, 8)}`
        : portable;
      const result = await api<ReadResponse2>(
        projectPath("/api/workflows", requestProject),
        {
          method: "POST",
          body: JSON.stringify({
            key,
            name: name.trim(),
            holder,
            ...(selected ? { template_id: selected.id } : {}),
          }),
        },
      );
      await onCreated(result.key, selected);
      onClose();
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog
      open={open}
      onClose={() => !busy && onClose()}
      fullWidth
      maxWidth="md"
    >
      <DialogTitle>Choose a workflow</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Typography>
            Choose a starter or begin with a blank workflow. Relay copies the
            starter's files into your project so you can edit them.
          </Typography>
          {loading && (
            <Typography role="status">Loading starter workflows…</Typography>
          )}
          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" },
              gap: 2,
            }}
          >
            {templates.map((template) => (
              <Paper
                key={template.id}
                component="article"
                aria-label={template.name}
                variant="outlined"
                sx={{ p: 2 }}
              >
                <Stack spacing={1}>
                  <Typography variant="h6">{template.name}</Typography>
                  <Typography>{template.description}</Typography>
                  <Typography
                    aria-label={`${template.name} job preview`}
                    variant="body2"
                  >
                    {template.jobs.join(" → ")}
                  </Typography>
                  <Typography variant="body2">
                    {templateSize(template)}
                  </Typography>
                  <Typography variant="body2">
                    Requires: {template.required_agents}
                  </Typography>
                  {template.default && (
                    <Typography variant="body2">
                      Needs Claude Code with an Opus model and one other coding
                      agent. Choose Ask an agent for a smaller first run.
                    </Typography>
                  )}
                  <Typography variant="body2">
                    Inputs:{" "}
                    {Object.entries(template.inputs)
                      .map(
                        ([key, input]) =>
                          `${key} (${inputTypeLabel(input.type)})`,
                      )
                      .join(", ")}
                  </Typography>
                  <Button
                    variant={
                      selected?.id === template.id ? "contained" : "outlined"
                    }
                    aria-pressed={selected?.id === template.id}
                    onClick={() => {
                      setSelected(template);
                      setName(template.name);
                    }}
                    disabled={busy || loading}
                  >
                    Use {template.name}
                  </Button>
                </Stack>
              </Paper>
            ))}
          </Box>
          <Button
            variant={selected === null ? "contained" : "outlined"}
            aria-pressed={selected === null}
            onClick={() => {
              setSelected(null);
              setName("New workflow");
            }}
            disabled={busy || loading}
          >
            Blank workflow
          </Button>
          {!selected && (
            <TextField
              autoFocus
              label="Workflow name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              disabled={busy}
            />
          )}
          {error && (
            <Alert
              severity="error"
              action={
                <Button
                  onClick={() => setCheck((value) => value + 1)}
                  disabled={busy}
                >
                  Try again
                </Button>
              }
            >
              {error}
            </Alert>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>
          Cancel
        </Button>
        <Button
          variant="contained"
          onClick={() => void create()}
          disabled={busy || loading || !name.trim()}
        >
          Create workflow
        </Button>
      </DialogActions>
    </Dialog>
  );
}
