import {
  Alert,
  Button,
  List,
  ListItem,
  ListItemText,
  Stack,
  Typography,
} from "@mui/material";
import { useEffect, useRef, useState } from "react";

import {
  api,
  errorMessage,
  importGitHubWorkflow,
  readGitHubWorkflows,
} from "../api";
import { projectPath } from "../navigation";
import type {
  GitHubWorkflowFile,
  GitHubWorkflowImport,
  WorkflowCreatedResponse,
} from "../types";
import { encoded } from "./ActionsWorkflowWorkspaceShared";

/** A converted file that Create workflow can open. */
export interface ImportedWorkflow {
  file: GitHubWorkflowFile;
  conversion: GitHubWorkflowImport;
}

/**
 * Create a blank workflow under the suggested key and keep the converted YAML
 * as its unsaved draft, so opening it shows the draft and Save validates it.
 */
export async function createImportedWorkflow(
  requestProject: string | null,
  holder: string,
  { file, conversion }: ImportedWorkflow,
): Promise<string> {
  const created = await api<WorkflowCreatedResponse>(
    projectPath("/api/workflows", requestProject),
    {
      method: "POST",
      body: JSON.stringify({
        key: conversion.suggested_key,
        name: file.name,
        holder,
      }),
    },
  );
  await api(
    projectPath(`/api/workflows/${encoded(created.key)}/draft`, requestProject),
    {
      method: "POST",
      body: JSON.stringify({
        yaml: conversion.yaml,
        prompts: {},
        base_hash: created.base_hash,
        holder,
      }),
    },
  );
  return created.key;
}

function Sentences({ label, items }: { label: string; items: string[] }) {
  return (
    <>
      <Typography variant="subtitle1" component="h3">
        {label}
      </Typography>
      <List dense disablePadding aria-label={label}>
        {items.map((item, index) => (
          <ListItem key={index} disableGutters>
            <ListItemText primary={item} />
          </ListItem>
        ))}
      </List>
    </>
  );
}

interface GitHubImportPanelProps {
  requestProject: string | null;
  disabled: boolean;
  onChange: (imported: ImportedWorkflow | null) => void;
}

/** List `.github/workflows` files, convert the chosen one, and show its changes. */
export function GitHubImportPanel({
  requestProject,
  disabled,
  onChange,
}: GitHubImportPanelProps) {
  const [files, setFiles] = useState<GitHubWorkflowFile[] | null>(null);
  const [chosen, setChosen] = useState<GitHubWorkflowFile | null>(null);
  const [conversion, setConversion] = useState<GitHubWorkflowImport | null>(
    null,
  );
  const [converting, setConverting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [check, setCheck] = useState(0);
  const request = useRef(0);

  useEffect(() => {
    const abort = new AbortController();
    setFiles(null);
    setError(null);
    void readGitHubWorkflows(requestProject, abort.signal)
      .then((value) => {
        if (!abort.signal.aborted) setFiles(value.files);
      })
      .catch((caught: unknown) => {
        if (abort.signal.aborted) return;
        setFiles([]);
        setError(errorMessage(caught));
      });
    return () => abort.abort();
  }, [requestProject, check]);

  async function convert(file: GitHubWorkflowFile) {
    // Only the latest choice may report back.
    const current = ++request.current;
    setChosen(file);
    setConversion(null);
    setError(null);
    setConverting(true);
    onChange(null);
    try {
      const result = await importGitHubWorkflow(requestProject, file.path);
      if (current !== request.current) return;
      setConversion(result);
      onChange({ file, conversion: result });
    } catch (caught) {
      if (current === request.current) setError(errorMessage(caught));
    } finally {
      if (current === request.current) setConverting(false);
    }
  }

  return (
    <Stack
      spacing={1}
      component="section"
      aria-label="Import from GitHub Actions"
    >
      <Typography>
        Choose a file from .github/workflows. Relay converts a copy and opens it
        as an unsaved draft; the original file does not change.
      </Typography>
      {files === null && (
        <Typography role="status">Loading GitHub Actions workflows…</Typography>
      )}
      {files?.length === 0 && !error && (
        <Typography>
          No .yml or .yaml files were found in .github/workflows.
        </Typography>
      )}
      {files?.map((file) => (
        <Button
          key={file.path}
          variant={chosen?.path === file.path ? "contained" : "outlined"}
          aria-pressed={chosen?.path === file.path}
          onClick={() => void convert(file)}
          disabled={disabled}
          sx={{ justifyContent: "flex-start", overflowWrap: "anywhere" }}
        >
          {file.name} · {file.path}
        </Button>
      ))}
      {converting && (
        <Typography role="status">Converting {chosen?.path}…</Typography>
      )}
      {conversion &&
        (conversion.changes.length ? (
          <Sentences label="Changes" items={conversion.changes} />
        ) : (
          <Typography variant="body2">This file needed no changes.</Typography>
        ))}
      {conversion && conversion.unresolved.length > 0 && (
        <Sentences label="Check by hand" items={conversion.unresolved} />
      )}
      {error && (
        <Alert
          severity="error"
          action={
            <Button
              onClick={() =>
                chosen ? void convert(chosen) : setCheck((value) => value + 1)
              }
              disabled={disabled || converting}
            >
              Try again
            </Button>
          }
        >
          {error}
        </Alert>
      )}
    </Stack>
  );
}
