import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Button,
  Stack,
  Typography,
} from "@mui/material";
import { useEffect, useMemo, useState } from "react";
import { api, errorMessage } from "../api";
import { actionsGraph, parseActions } from "../actions-workflow";
import { projectPath, viewHref } from "../navigation";
import type { WorkflowDocumentResponse } from "../types";
import { FlowCanvas } from "./FlowCanvas";
import { ViewSkeleton } from "./ViewSkeleton";

export function ReusableWorkflowPreview({
  reference,
  project,
  loop = false,
  expanded = false,
}: {
  reference: string;
  project: string | null;
  loop?: boolean;
  expanded?: boolean;
}) {
  const [open, setOpen] = useState(expanded);
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const key = reference.replace(/^\.\/.relay\/workflows\//, "");
  useEffect(() => {
    if (!open || !key || key.includes("${{")) return;
    const controller = new AbortController();
    setText("");
    setError("");
    void api<WorkflowDocumentResponse>(
      projectPath(
        `/api/workflows/${key.split("/").map(encodeURIComponent).join("/")}`,
        project,
      ),
      { signal: controller.signal },
    )
      .then((result) => {
        if (!controller.signal.aborted) setText(result.yaml);
      })
      .catch((caught) => {
        if (!controller.signal.aborted) setError(errorMessage(caught));
      });
    return () => controller.abort();
  }, [open, key, project]);
  const graph = useMemo(() => actionsGraph(parseActions(text).value), [text]);
  return (
    <Accordion expanded={open} onChange={(_, value) => setOpen(value)}>
      <AccordionSummary>
        {loop ? "Loop body" : "Reusable workflow"}: {key}
      </AccordionSummary>
      <AccordionDetails>
        <Stack spacing={1}>
          {error ? (
            <Alert severity="error">{error}</Alert>
          ) : text ? (
            <Box>
              <Typography>{graph.nodes.length} child jobs</Typography>
              <FlowCanvas
                runMode
                nodes={graph.nodes.map((node) => ({ ...node, type: "runJob" }))}
                edges={graph.edges}
              />
            </Box>
          ) : key.includes("${{") ? (
            <Typography>
              The workflow is selected when this job runs.
            </Typography>
          ) : (
            <ViewSkeleton view="child workflow" header={false} />
          )}
          <Button
            component="a"
            href={viewHref("workflows", project, { workflow: key })}
          >
            Open {loop ? "loop body" : "child workflow"} to edit
          </Button>
        </Stack>
      </AccordionDetails>
    </Accordion>
  );
}
