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
import { useState } from "react";

import { api, errorMessage } from "../api";
import { projectPath } from "../navigation";
import type {
  LaunchPreview as LaunchPreviewResult,
  PreviewJob,
  PreviewStep,
  PreviewText,
} from "../types";
import { ActionIcon } from "./ActionIcon";
import type { LaunchValues } from "./LaunchInputs";

function RuntimeNote({ value }: { value: PreviewText | null }) {
  if (!value?.runtime.length) return null;
  return (
    <Typography variant="body2" color="text.secondary">
      Filled in when the step runs: {value.runtime.join(", ")}
    </Typography>
  );
}

function Text({ label, value }: { label: string; value: PreviewText }) {
  return (
    <Box>
      <Typography variant="subtitle2">{label}</Typography>
      <Box component="pre" className="activity-text" sx={{ m: 0 }}>
        {value.text}
      </Box>
      <RuntimeNote value={value} />
    </Box>
  );
}

function StepPreview({ step }: { step: PreviewStep }) {
  const route = [step.agents?.text, step.model?.text, step.effort?.text]
    .filter(Boolean)
    .join(" · ");
  return (
    <Stack spacing={1} component="section" aria-label={`Step ${step.name}`}>
      <Typography variant="subtitle1">{step.name}</Typography>
      {step.kind === "agent" && (
        <Typography variant="body2">
          {route || "Uses the project or global default agent and model."}
        </Typography>
      )}
      {step.prompt_files.map((prompt) => (
        <Box component="details" key={prompt.reference}>
          <Box component="summary">
            {prompt.reference} · {prompt.bytes.toLocaleString()} bytes ·{" "}
            <Box component="code">{prompt.sha256.slice(0, 12)}</Box>
          </Box>
          <Box component="pre" className="activity-text">
            {prompt.text}
          </Box>
          {prompt.truncated && (
            <Typography variant="body2">
              Showing the first 64 KiB. The agent receives the whole file.
            </Typography>
          )}
        </Box>
      ))}
      {step.prompt_files_runtime && (
        <Text
          label="Prompt files (chosen when the step runs)"
          value={step.prompt_files_runtime}
        />
      )}
      {step.prompt && <Text label="Step prompt" value={step.prompt} />}
      {step.report && <Text label="Report contract" value={step.report} />}
      {step.command && <Text label="Command" value={step.command} />}
      {step.kind === "action" && step.uses && (
        <Typography variant="body2">
          Runs <Box component="code">{step.uses}</Box>
          {step.repeat ? `, up to ${step.repeat.text} times` : ""}
          {step.steps.length || step.jobs.length
            ? ":"
            : "; its steps expand when the job starts."}
        </Typography>
      )}
      {step.repeat && <RuntimeNote value={step.repeat} />}
      {step.steps.length > 0 && (
        <Stack spacing={1} sx={{ pl: 2 }}>
          {step.steps.map((child) => (
            <StepPreview key={child.id} step={child} />
          ))}
        </Stack>
      )}
      {step.jobs.length > 0 && (
        <Stack spacing={1} sx={{ pl: 2 }}>
          {step.jobs.map((job) => (
            <JobPreview key={job.id} job={job} />
          ))}
        </Stack>
      )}
    </Stack>
  );
}

function JobPreview({ job }: { job: PreviewJob }) {
  return (
    <Stack spacing={1} component="section" aria-label={`Job ${job.name}`}>
      <Typography variant="h6" component="h3">
        {job.name}
      </Typography>
      {job.needs.length > 0 && (
        <Typography variant="body2" color="text.secondary">
          Runs after {job.needs.join(", ")}
        </Typography>
      )}
      {job.matrix && (
        <Typography variant="body2" color="text.secondary">
          Runs once per matrix combination.
        </Typography>
      )}
      {job.uses && (
        <Typography variant="body2">
          Calls <Box component="code">{job.uses}</Box>
          {job.jobs.length ? ":" : "."}
        </Typography>
      )}
      {job.steps.map((step) => (
        <StepPreview key={step.id} step={step} />
      ))}
      {job.jobs.length > 0 && (
        <Stack spacing={1} sx={{ pl: 2 }}>
          {job.jobs.map((child) => (
            <JobPreview key={child.id} job={child} />
          ))}
        </Stack>
      )}
    </Stack>
  );
}

/** A read-only look at each step's launch-static instructions before running. */
export function LaunchPreview({
  workflowKey,
  requestProject,
  inputs,
  notes,
}: {
  workflowKey: string;
  requestProject: string | null;
  inputs: LaunchValues;
  notes: string[];
}) {
  const [result, setResult] = useState<LaunchPreviewResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  async function load(): Promise<void> {
    setLoading(true);
    setError(null);
    try {
      const path = `/api/workflows/${workflowKey.split("/").map(encodeURIComponent).join("/")}/preview`;
      // Inputs travel in the body so launch values never appear in a URL.
      setResult(
        await api<LaunchPreviewResult>(projectPath(path, requestProject), {
          method: "POST",
          body: JSON.stringify({ inputs, ...(notes.length ? { notes } : {}) }),
        }),
      );
    } catch (caught) {
      setResult(null);
      setError(errorMessage(caught));
    } finally {
      setLoading(false);
    }
  }
  return (
    <Accordion>
      <AccordionSummary expandIcon={<ActionIcon name="down" />}>
        Preview step instructions
      </AccordionSummary>
      <AccordionDetails>
        <Stack spacing={2}>
          <Typography variant="body2">
            See what each step will be told with the inputs above. Nothing runs
            and no agent is contacted, so model availability is still checked at
            launch.
          </Typography>
          <Box>
            <Button
              variant="outlined"
              disabled={loading}
              onClick={() => void load()}
            >
              {result ? "Refresh preview" : "Preview"}
            </Button>
          </Box>
          {error && <Alert severity="error">{error}</Alert>}
          {result && (
            <>
              <Typography>Run title: {result.run_name.text}</Typography>
              {result.notes && (
                <Box component="section" aria-label="Workflow notes">
                  <Typography variant="subtitle2">
                    Workflow notes given to every agent step
                  </Typography>
                  <Box component="pre" className="activity-text" sx={{ m: 0 }}>
                    {result.notes}
                  </Box>
                </Box>
              )}
              {result.jobs.map((job) => (
                <JobPreview key={job.id} job={job} />
              ))}
              {result.truncated && (
                <Alert severity="info">
                  The preview stops before the response limit. Later jobs are
                  not shown.
                </Alert>
              )}
            </>
          )}
        </Stack>
      </AccordionDetails>
    </Accordion>
  );
}
