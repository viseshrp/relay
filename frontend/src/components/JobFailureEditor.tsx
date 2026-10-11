import {
  Alert,
  Button,
  Checkbox,
  FormControlLabel,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useState } from "react";
import type { ActionJob } from "../actions-workflow";

export function JobFailureEditor({
  job,
  change,
}: {
  job: ActionJob;
  change: (value: ActionJob) => void;
}) {
  const agents = (job.steps ?? []).filter(
    (step) => step.uses === "relay/agent@v1",
  );
  const [repair, setRepair] = useState("");
  const policy =
    agents.length &&
    agents.every(
      (step) =>
        step.with?.["auto-retry"] === true ||
        step.with?.["auto-retry"] === "true",
    )
      ? "retry"
      : agents.some(
            (step) =>
              step.with?.["auto-retry"] === false ||
              step.with?.["auto-retry"] === "false",
          )
        ? "stop"
        : "inherit";
  function configure(retry: boolean, limit?: number) {
    change({
      ...job,
      steps: job.steps?.map((step) =>
        step.uses === "relay/agent@v1"
          ? {
              ...step,
              with: {
                ...step.with,
                "auto-retry": retry,
                ...(limit ? { "retry-limit": limit } : {}),
              },
            }
          : step,
      ),
    });
  }
  return (
    <Stack spacing={2}>
      {agents.length > 0 ? (
        <>
          <TextField
            select
            label="When this job fails"
            value={policy}
            onChange={(event) => {
              if (event.target.value === "inherit")
                change({
                  ...job,
                  steps: job.steps?.map((step) => {
                    const inputs = { ...step.with };
                    delete inputs["auto-retry"];
                    delete inputs["retry-limit"];
                    return step.uses === "relay/agent@v1"
                      ? { ...step, with: inputs }
                      : step;
                  }),
                });
              else configure(event.target.value === "retry");
            }}
          >
            <MenuItem value="inherit">
              Use the workflow recovery default
            </MenuItem>
            <MenuItem value="stop">Stop and tell me</MenuItem>
            <MenuItem value="retry">Retry up to N times</MenuItem>
          </TextField>
          {policy === "retry" && (
            <TextField
              select
              label="Maximum automatic retries per agent step"
              value={String(agents[0].with?.["retry-limit"] ?? 2)}
              onChange={(event) => configure(true, Number(event.target.value))}
            >
              <MenuItem value="1">1</MenuItem>
              <MenuItem value="2">2</MenuItem>
            </TextField>
          )}
        </>
      ) : (
        <Typography>
          This job stops and tells you when a step fails. Automatic provider
          recovery applies to agent steps.
        </Typography>
      )}
      <Typography variant="body2">
        Retries preserve the original prompts, model, permissions, and lifetime
        budget. Usage limits require a confirmed reset; human waits remain your
        decision.
      </Typography>
      <FormControlLabel
        label="Continue after this job fails"
        control={
          <Checkbox
            checked={job["continue-on-error"] === true}
            onChange={(event) =>
              change({ ...job, "continue-on-error": event.target.checked })
            }
          />
        }
      />
      <Typography component="h3" variant="subtitle1">
        Ask a fixer agent and re-check
      </Typography>
      <TextField
        label="Fix-and-check workflow file"
        value={repair}
        onChange={(event) => setRepair(event.target.value)}
        placeholder="./.relay/workflows/fix-and-check.yaml"
        helperText="Choose a reusable workflow containing the fixer and verifier. Its outputs decide whether another round is needed."
      />
      <Button
        disabled={!/^\.\/\.relay\/workflows\/.+\.ya?ml$/.test(repair)}
        onClick={() => {
          change({
            ...job,
            steps: [
              ...(job.steps ?? []),
              {
                id: "fix_and_check",
                uses: "relay/loop@v1",
                if: "${{ failure() }}",
                with: {
                  workflow: repair,
                  "max-iterations": "3",
                  "until-output": "passed",
                  equals: "true",
                },
              },
            ],
          });
          setRepair("");
        }}
      >
        Add bounded fix-and-check loop
      </Button>
      {(job.steps ?? []).some((step) => step.id === "fix_and_check") && (
        <Alert severity="info">
          The loop is an explicit recovery step. Edit its round limit, inputs,
          and completion output in Steps; existing failure conclusions are
          preserved.
        </Alert>
      )}
    </Stack>
  );
}
