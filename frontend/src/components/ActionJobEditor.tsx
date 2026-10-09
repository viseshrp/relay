import {
  Autocomplete,
  Box,
  Button,
  Checkbox,
  FormControlLabel,
  MenuItem,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
} from "@mui/material";
import { useState } from "react";
import type { ActionWorkflow } from "../actions-workflow";
import type { AgentRecord, ProviderDefaults } from "../types";
import type { LanguageManifest } from "../workflow-language";
import { expressionSuggestions } from "../workflow-language";
import { ActionBuiltinFields } from "./ActionBuiltinFields";
import { SchemaFields } from "./SchemaFields";
import { StructuredValueField } from "./StructuredValueField";
import type { PromptEdits } from "./PromptFilesEditor";
import { MatrixEditor } from "./MatrixEditor";
import { ConcurrencyEditor } from "./ConcurrencyEditor";
import { JobFailureEditor } from "./JobFailureEditor";
import { ExpressionField } from "./ExpressionField";

export function ActionJobEditor({
  workflow,
  jobId,
  index,
  onIndex,
  manifest,
  change,
  onMove,
  agents,
  defaults,
  defaultModel,
  project,
  workflowKey,
  edits,
  onEdits,
}: {
  workflow: ActionWorkflow;
  jobId: string;
  index: number;
  onIndex: (index: number) => void;
  manifest: LanguageManifest;
  change: (path: Array<string | number>, value: unknown) => void;
  onMove: (from: number, to: number) => void;
  agents: AgentRecord[];
  defaults: Record<string, ProviderDefaults>;
  defaultModel: string;
  project: string | null;
  workflowKey: string;
  edits: PromptEdits;
  onEdits: (reference: string, edit: PromptEdits[string]) => void;
}) {
  const [tab, setTab] = useState("General");
  const job = workflow.jobs[jobId];
  const step = job?.steps?.[index];
  if (!job) return null;
  const field = (key: string, value: unknown) =>
    change(["jobs", jobId, key], value);
  const stepField = (key: string, value: unknown) =>
    change(["jobs", jobId, "steps", index, key], value);
  const input = (key: string, value: unknown) =>
    change(
      key === "__all__"
        ? ["jobs", jobId, "steps", index, "with"]
        : ["jobs", jobId, "steps", index, "with", key],
      value,
    );
  const suggestions = expressionSuggestions(workflow, jobId);
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
        {tab === "Steps" && (
          <Stack spacing={2}>
            {job.uses ? (
              <StructuredValueField
                label="Reusable inputs"
                value={job.with}
                object
                onChange={(value) => field("with", value)}
              />
            ) : (
              <>
                <TextField
                  select
                  label="Ordered step"
                  value={Math.min(index, (job.steps?.length ?? 1) - 1)}
                  onChange={(event) => onIndex(Number(event.target.value))}
                >
                  {job.steps?.map((item, offset) => (
                    <MenuItem key={offset} value={offset}>
                      {offset + 1}.{" "}
                      {item.name || item.id || item.uses || "Run script"}
                    </MenuItem>
                  ))}
                </TextField>
                {step && (
                  <>
                    <TextField
                      label="Step ID"
                      value={step.id ?? ""}
                      onChange={(event) =>
                        stepField("id", event.target.value || undefined)
                      }
                    />
                    <TextField
                      label="Step name"
                      slotProps={{ htmlInput: { maxLength: 256 } }}
                      value={step.name ?? ""}
                      onChange={(event) =>
                        stepField("name", event.target.value || undefined)
                      }
                    />
                    <TextField
                      select
                      label="Step type"
                      value={step.uses ?? "script"}
                      onChange={(event) =>
                        change(
                          ["jobs", jobId, "steps", index],
                          event.target.value === "script"
                            ? {
                                name: step.name,
                                id: step.id,
                                run: "echo Ready",
                              }
                            : {
                                name: step.name,
                                id: step.id,
                                uses: event.target.value,
                                with: Object.fromEntries(
                                  (
                                    manifest.builtin_inputs[event.target.value]
                                      ?.required ?? []
                                  ).map((key) => [
                                    key,
                                    key === "max-iterations" ? "3" : "",
                                  ]),
                                ),
                              },
                        )
                      }
                    >
                      <MenuItem value="script">Run a script</MenuItem>
                      {manifest.builtins.map((reference) => (
                        <MenuItem key={reference} value={reference}>
                          {reference.replace("relay/", "").replace("@v1", "")}
                        </MenuItem>
                      ))}
                      {step.uses?.startsWith("./") && (
                        <MenuItem value={step.uses}>{step.uses}</MenuItem>
                      )}
                    </TextField>
                    <TextField
                      label="Action reference"
                      value={step.uses ?? ""}
                      onChange={(event) =>
                        change(
                          ["jobs", jobId, "steps", index],
                          event.target.value
                            ? {
                                ...step,
                                uses: event.target.value,
                                run: undefined,
                              }
                            : { ...step, uses: undefined, run: "echo Ready" },
                        )
                      }
                    />
                    {step.uses ? (
                      <ActionBuiltinFields
                        step={step}
                        agents={agents}
                        defaults={defaults}
                        defaultModel={defaultModel}
                        manifest={manifest}
                        project={project}
                        workflowKey={workflowKey}
                        workflow={workflow}
                        jobId={jobId}
                        edits={edits}
                        onEdits={onEdits}
                        onChange={input}
                      />
                    ) : (
                      <>
                        <TextField
                          label="Script"
                          multiline
                          minRows={3}
                          value={step.run ?? ""}
                          onChange={(event) =>
                            stepField("run", event.target.value)
                          }
                        />
                        <TextField
                          select
                          label="Shell"
                          value={step.shell ?? ""}
                          onChange={(event) =>
                            stepField("shell", event.target.value || undefined)
                          }
                        >
                          <MenuItem value="">Host default</MenuItem>
                          {["bash", "sh", "pwsh", "python"].map((shell) => (
                            <MenuItem value={shell} key={shell}>
                              {shell}
                            </MenuItem>
                          ))}
                        </TextField>
                        <TextField
                          label="Working directory"
                          value={step["working-directory"] ?? ""}
                          onChange={(event) =>
                            stepField(
                              "working-directory",
                              event.target.value || undefined,
                            )
                          }
                        />
                        <Typography variant="body2">
                          The script runs through the selected shell using an
                          argument vector and the captured job working
                          directory.
                        </Typography>
                      </>
                    )}
                    <ExpressionField
                      label="Step condition"
                      value={step.if ?? ""}
                      suggestions={suggestions}
                      onChange={(value) => stepField("if", value || undefined)}
                    />
                    <TextField
                      label="Timeout (minutes or expression)"
                      value={step["timeout-minutes"] ?? ""}
                      onChange={(event) =>
                        stepField(
                          "timeout-minutes",
                          event.target.value.includes("${{")
                            ? event.target.value
                            : event.target.value
                              ? Number(event.target.value)
                              : undefined,
                        )
                      }
                    />
                    <StructuredValueField
                      label="Step environment variables"
                      object
                      value={step.env}
                      onChange={(value) => stepField("env", value)}
                    />
                    <FormControlLabel
                      label="Continue after this step fails"
                      control={
                        <Checkbox
                          checked={step["continue-on-error"] === true}
                          onChange={(event) =>
                            stepField("continue-on-error", event.target.checked)
                          }
                        />
                      }
                    />
                    <Stack direction="row" spacing={1}>
                      <Button
                        disabled={index === 0}
                        onClick={() => onMove(index, index - 1)}
                      >
                        Move earlier
                      </Button>
                      <Button
                        disabled={index >= (job.steps?.length ?? 0) - 1}
                        onClick={() => onMove(index, index + 1)}
                      >
                        Move later
                      </Button>
                      <Button
                        onClick={() => {
                          change(["jobs", jobId, "steps", index], undefined);
                          onIndex(Math.max(0, index - 1));
                        }}
                      >
                        Remove step
                      </Button>
                    </Stack>
                  </>
                )}
                <Button
                  onClick={() => {
                    change(["jobs", jobId, "steps", job.steps?.length ?? 0], {
                      run: "echo Ready",
                    });
                    onIndex(job.steps?.length ?? 0);
                  }}
                >
                  Add step
                </Button>
              </>
            )}
          </Stack>
        )}
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
