import {
  Alert,
  Button,
  Checkbox,
  FormControlLabel,
  MenuItem,
  Stack,
  Typography,
} from "@mui/material";
import { useState } from "react";
import type { ActionJob } from "../actions-workflow";
import { currentBuiltin, isBuiltin } from "../builtin-actions";
import { GUIDE, inputHelp, propertyHelp } from "../field-help";
import type { LanguageManifest } from "../workflow-language";
import { HelpControl, HelpSelectField, HelpTextField } from "./HelpTip";

export function JobFailureEditor({
  job,
  manifest,
  change,
}: {
  job: ActionJob;
  manifest: LanguageManifest;
  change: (value: ActionJob) => void;
}) {
  const agents = (job.steps ?? []).filter((step) =>
    isBuiltin(step.uses, "agent"),
  );
  const [repair, setRepair] = useState("");
  const agent = currentBuiltin(manifest, "agent");
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
        isBuiltin(step.uses, "agent")
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
          <HelpSelectField
            topic={inputHelp(
              manifest,
              agent,
              "auto-retry",
              "When this job fails",
            )}
            label="When this job fails"
            width="wide"
            value={policy}
            onChange={(event) => {
              if (event.target.value === "inherit")
                change({
                  ...job,
                  steps: job.steps?.map((step) => {
                    const inputs = { ...step.with };
                    delete inputs["auto-retry"];
                    delete inputs["retry-limit"];
                    return isBuiltin(step.uses, "agent")
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
          </HelpSelectField>
          {policy === "retry" && (
            <HelpSelectField
              topic={inputHelp(
                manifest,
                agent,
                "retry-limit",
                "Maximum automatic retries per agent step",
              )}
              label="Maximum automatic retries per agent step"
              width="wide"
              value={String(agents[0].with?.["retry-limit"] ?? 2)}
              onChange={(event) => configure(true, Number(event.target.value))}
            >
              <MenuItem value="1">1</MenuItem>
              <MenuItem value="2">2</MenuItem>
            </HelpSelectField>
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
      <HelpControl
        topic={propertyHelp(
          manifest,
          "job-factory.continue-on-error",
          "Continue after this job fails",
        )}
      >
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
      </HelpControl>
      <Typography component="h3" variant="subtitle1">
        Ask a fixer agent and re-check
      </Typography>
      <HelpTextField
        topic={{
          title: "Fix-and-check workflow file",
          description:
            "A reusable workflow under ./.relay/workflows/ that runs a fixer and a verifier. Its passed output decides whether another round runs, up to three rounds.",
          guide: GUIDE.recovery,
        }}
        label="Fix-and-check workflow file"
        width="wide"
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
                uses: currentBuiltin(manifest, "loop"),
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
