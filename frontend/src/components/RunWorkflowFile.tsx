import { Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle, Stack, Typography } from "@mui/material";
import { useEffect, useMemo, useState } from "react";
import { api, errorMessage } from "../api";
import { readableWorkflowYaml } from "../source-format";
import type { CapturedRunWorkflow } from "../types";

export function RunWorkflowFile({ runId, onClose, onEdit }: {
  runId: string; onClose: () => void; onEdit: (key: string) => void;
}) {
  const [workflow, setWorkflow] = useState<CapturedRunWorkflow | null>(null);
  const [error, setError] = useState<string | null>(null);
  const displayed = useMemo(() => workflow && !workflow.truncated ? readableWorkflowYaml(workflow.yaml) : workflow?.yaml ?? "", [workflow]);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError(null); setWorkflow(null);
    void api<CapturedRunWorkflow>(`/api/runs/${encodeURIComponent(runId)}/workflow`, { signal: controller.signal })
      .then((response) => { if (!controller.signal.aborted) setWorkflow(response); })
      .catch((caught: unknown) => { if (!controller.signal.aborted) setError(errorMessage(caught)); });
    return () => controller.abort();
  }, [runId, revision]);
  return <Dialog open fullWidth maxWidth="lg" onClose={onClose} aria-labelledby="run-workflow-title">
    <DialogTitle id="run-workflow-title">Workflow file</DialogTitle>
    <DialogContent><Stack spacing={2}>
      <Typography>This workflow was captured when the run started.</Typography>
      {error && <Alert severity="error" action={<Button onClick={() => setRevision((value) => value + 1)}>Retry</Button>}>{error}</Alert>}
      {!workflow && !error && <Typography aria-busy>Loading captured workflow…</Typography>}
      {workflow && <>
        <Typography variant="subtitle2">{workflow.workflow_key}</Typography>
        <Typography variant="caption" className="mono-wrap">SHA-256: {workflow.sha256}</Typography>
        {workflow.truncated && <Alert severity="info">This workflow exceeds the preview limit. The hash covers the full captured workflow.</Alert>}
        <Box component="pre" aria-label="Captured workflow YAML" className="captured-source" sx={{ overflow: "auto", maxHeight: "65vh" }}>{displayed}</Box>
      </>}
    </Stack></DialogContent>
    <DialogActions>
      {workflow && <Button onClick={() => onEdit(workflow.workflow_key)}>Edit current workflow</Button>}
      <Button onClick={onClose}>Close</Button>
    </DialogActions>
  </Dialog>;
}
