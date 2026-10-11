import { ReusableWorkflowPreview } from "./ReusableWorkflowPreview";
import { ActionJobSteps } from "./ActionJobSteps";
import {
  Autocomplete,
  Box,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";

import { SchemaFields } from "./SchemaFields";
import { StructuredValueField } from "./StructuredValueField";

import { MatrixEditor } from "./MatrixEditor";
import { ConcurrencyEditor } from "./ConcurrencyEditor";
import { JobFailureEditor } from "./JobFailureEditor";
import { ExpressionField } from "./ExpressionField";
import type { ActionJobEditorState } from "./useActionJobEditor";
export function ActionJobEditorView({
  state,
}: {
  state: ActionJobEditorState;
}) {
  const {
    tab,
    setTab,
    job,
    field,
    workflow,
    jobId,
    suggestions,
    change,
    manifest,
    project,
  } = state;
  return (
    <Stack spacing={2}>
      <Tabs
        variant="scrollable"
        value={tab}
        onChange={(_, value: string) => setTab(value)}
        aria-label="Job settings tabs"
      >
        {["General", "Steps", "Outputs", "Environment", "When it fails"].map(
          (label) => (
            <Tab key={label} value={label} label={label} />
          ),
        )}
      </Tabs>
      <Box role="tabpanel" aria-label={tab}>
        {tab === "General" && (
          <Stack spacing={2}>
            <TextField
              label="Job name"
              slotProps={{ htmlInput: { maxLength: 256 } }}
              value={job.name ?? ""}
              onChange={(event) => field("name", event.target.value)}
            />
            <Autocomplete
              multiple
              options={Object.keys(workflow.jobs).filter((id) => id !== jobId)}
              value={
                typeof job.needs === "string" ? [job.needs] : (job.needs ?? [])
              }
              onChange={(_, selected) => field("needs", selected)}
              renderInput={(parameters) => (
                <TextField
                  {...parameters}
                  label="Start after"
                  helperText="Dependencies must finish before this job starts."
                />
              )}
            />
            <ExpressionField
              label="Job condition"
              value={job.if ?? ""}
              suggestions={suggestions}
              onChange={(value) => field("if", value || undefined)}
            />
            <TextField
              label="Job timeout (minutes)"
              value={job["timeout-minutes"] ?? ""}
              onChange={(event) =>
                field(
                  "timeout-minutes",
                  event.target.value.includes("${{")
                    ? event.target.value
                    : event.target.value
                      ? Number(event.target.value)
                      : undefined,
                )
              }
            />
            <TextField
              label="Reusable workflow"
              value={job.uses ?? ""}
              onChange={(event) => {
                if (event.target.value)
                  change(["jobs", jobId], {
                    ...job,
                    uses: event.target.value,
                    steps: undefined,
                  });
                else field("uses", undefined);
              }}
            />
            {job.uses && (
              <ReusableWorkflowPreview reference={job.uses} project={project} />
            )}
            <MatrixEditor
              value={job.strategy}
              onChange={(value) =>
                field("strategy", value as Record<string, unknown>)
              }
            />
            <ConcurrencyEditor
              value={job.concurrency}
              onChange={(value) => field("concurrency", value)}
            />
            <SchemaFields
              label="Job"
              manifest={manifest}
              type={job.uses ? "workflow-job" : "job-factory"}
              value={job}
              omit={[
                "name",
                "needs",
                "if",
                "timeout-minutes",
                "uses",
                "steps",
                "strategy",
                "concurrency",
                "outputs",
                "environment",
                "env",
                "continue-on-error",
              ]}
              onChange={field}
            />
          </Stack>
        )}
        {tab === "Steps" && <ActionJobSteps state={state} />}
        {tab === "Outputs" && (
          <Stack spacing={2}>
            <Typography>
              Outputs hand values to downstream jobs. Report actions retain the
              file when their format is label, json, or yaml; exists keeps a
              boolean.
            </Typography>
            <StructuredValueField
              label="Job outputs"
              object
              value={job.outputs}
              onChange={(value) => field("outputs", value)}
            />
          </Stack>
        )}
        {tab === "Environment" && (
          <Stack spacing={2}>
            <StructuredValueField
              label="Job environment variables"
              object
              value={job.env}
              onChange={(value) => field("env", value)}
            />
            <StructuredValueField
              label="Environment"
              value={job.environment}
              onChange={(value) => field("environment", value)}
            />
          </Stack>
        )}
        {tab === "When it fails" && (
          <JobFailureEditor
            job={job}
            change={(value) => change(["jobs", jobId], value)}
          />
        )}
      </Box>
    </Stack>
  );
}
