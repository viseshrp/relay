import { ReusableWorkflowPreview } from "./ReusableWorkflowPreview";
import { ActionJobSteps } from "./ActionJobSteps";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Autocomplete,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Stack,
  Tab,
  Tabs,
  Typography,
} from "@mui/material";
import { useState } from "react";

import { JOB_ID } from "../actions-workflow";
import { GUIDE, propertyHelp } from "../field-help";
import { ActionIcon } from "./ActionIcon";
import { HelpTextField } from "./HelpTip";
import { SchemaFields } from "./SchemaFields";
import { StructuredValueField } from "./StructuredValueField";

import { MatrixEditor } from "./MatrixEditor";
import { ConcurrencyEditor } from "./ConcurrencyEditor";
import { JobFailureEditor } from "./JobFailureEditor";
import { ExpressionField } from "./ExpressionField";
import type { ActionJobEditorState } from "./useActionJobEditor";

// Fields General shows outside Advanced, or that other tabs edit.
const SCHEMA_OMIT = [
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
];

function RenameJobDialog({
  jobId,
  others,
  onClose,
  onRename,
}: {
  jobId: string;
  others: string[];
  onClose: () => void;
  onRename: (id: string) => void;
}) {
  const [value, setValue] = useState(jobId);
  const next = value.trim();
  const problem = !JOB_ID.test(next)
    ? "Start with a letter or _, then use letters, digits, _, or -."
    : others.includes(next)
      ? "Another job already uses this ID."
      : "";
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>Rename job ID</DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Typography>
            Dependencies and needs references in expressions move to the new ID
            in the same edit. Undo restores them.
          </Typography>
          <HelpTextField
            topic={{
              title: "New job ID",
              description:
                "The key under jobs. Start with a letter or _, then use letters, digits, _, or -. It must differ from every other job's ID.",
              guide: GUIDE.jobs,
            }}
            label="New job ID"
            autoFocus
            value={value}
            error={Boolean(problem)}
            helperText={problem || " "}
            onChange={(event) => setValue(event.target.value)}
          />
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          disabled={Boolean(problem) || next === jobId}
          onClick={() => onRename(next)}
        >
          Rename
        </Button>
      </DialogActions>
    </Dialog>
  );
}

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
    onRename,
  } = state;
  const [renaming, setRenaming] = useState(false);
  const type = job.uses ? "workflow-job" : "job-factory";
  // A reusable job lacks some job fields; describe those as a job's.
  const help = (property: string, title: string, guide: string = GUIDE.jobs) =>
    propertyHelp(
      manifest,
      manifest.property_descriptions[`${type}.${property}`]
        ? `${type}.${property}`
        : `job-factory.${property}`,
      title,
      guide,
    );
  const properties = manifest.definitions[type]?.mapping?.properties ?? {};
  const advanced =
    job.uses !== undefined ||
    job.strategy !== undefined ||
    job.concurrency !== undefined ||
    Object.keys(properties).some(
      (key) => !SCHEMA_OMIT.includes(key) && key in job,
    );
  const others = Object.keys(workflow.jobs).filter((id) => id !== jobId);
  const jobName = (id: string) => {
    const name = workflow.jobs[id]?.name;
    return name ? `${name} (${id})` : id;
  };
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
            <HelpTextField
              topic={help("name", "Job name")}
              label="Job name"
              slotProps={{ htmlInput: { maxLength: 256 } }}
              value={job.name ?? ""}
              onChange={(event) => field("name", event.target.value)}
            />
            <Stack
              direction="row"
              spacing={1}
              sx={{ alignItems: "end", flexWrap: "wrap", gap: 1 }}
            >
              <HelpTextField
                topic={{
                  title: "Job ID",
                  description:
                    "The key under jobs that dependencies and expressions use to name this job. It never changes by itself; Rename job ID updates every reference.",
                  guide: GUIDE.jobs,
                }}
                label="Job ID"
                value={jobId}
                slotProps={{ input: { readOnly: true } }}
              />
              <Button onClick={() => setRenaming(true)}>Rename job ID</Button>
            </Stack>
            {renaming && (
              <RenameJobDialog
                jobId={jobId}
                others={others}
                onClose={() => setRenaming(false)}
                onRename={(id) => {
                  setRenaming(false);
                  onRename(id);
                }}
              />
            )}
            <Autocomplete
              multiple
              options={others}
              getOptionLabel={jobName}
              value={
                typeof job.needs === "string" ? [job.needs] : (job.needs ?? [])
              }
              onChange={(_, selected) => field("needs", selected)}
              renderInput={(parameters) => (
                <HelpTextField
                  {...parameters}
                  topic={help("needs", "Start after")}
                  label="Start after"
                  width="wide"
                  helperText="Dependencies must finish before this job starts."
                />
              )}
            />
            <ExpressionField
              label="Job condition"
              help={help("if", "Job condition", GUIDE.expressions)}
              value={job.if ?? ""}
              suggestions={suggestions}
              onChange={(value) => field("if", value || undefined)}
            />
            <HelpTextField
              topic={help("timeout-minutes", "Job timeout (minutes)")}
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
            <Accordion disableGutters defaultExpanded={advanced}>
              <AccordionSummary expandIcon={<ActionIcon name="down" />}>
                Advanced
              </AccordionSummary>
              <AccordionDetails>
                <Stack spacing={2}>
                  <HelpTextField
                    topic={propertyHelp(
                      manifest,
                      "workflow-job.uses",
                      "Reusable workflow",
                      GUIDE.reusable,
                    )}
                    label="Reusable workflow"
                    width="wide"
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
                    <ReusableWorkflowPreview
                      reference={job.uses}
                      project={project}
                    />
                  )}
                  <MatrixEditor
                    manifest={manifest}
                    value={job.strategy}
                    onChange={(value) =>
                      field("strategy", value as Record<string, unknown>)
                    }
                  />
                  <ConcurrencyEditor
                    manifest={manifest}
                    value={job.concurrency}
                    onChange={(value) => field("concurrency", value)}
                  />
                  <SchemaFields
                    label="Job"
                    manifest={manifest}
                    type={type}
                    value={job}
                    omit={SCHEMA_OMIT}
                    onChange={field}
                  />
                </Stack>
              </AccordionDetails>
            </Accordion>
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
              help={help("outputs", "Job outputs", GUIDE.outputs)}
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
              help={help("env", "Job environment variables", GUIDE.variables)}
              object
              value={job.env}
              onChange={(value) => field("env", value)}
            />
            <StructuredValueField
              label="Environment"
              help={help("environment", "Environment", GUIDE.variables)}
              value={job.environment}
              onChange={(value) => field("environment", value)}
            />
          </Stack>
        )}
        {tab === "When it fails" && (
          <JobFailureEditor
            job={job}
            manifest={manifest}
            change={(value) => change(["jobs", jobId], value)}
          />
        )}
      </Box>
    </Stack>
  );
}
