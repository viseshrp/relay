import { ScriptEditor } from "./ScriptEditor";
import {
  Button,
  Checkbox,
  FormControlLabel,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";

import { ActionBuiltinFields } from "./ActionBuiltinFields";

import { StructuredValueField } from "./StructuredValueField";

import { ExpressionField } from "./ExpressionField";
import type { ActionJobEditorState } from "./useActionJobEditor";
export function ActionJobSteps({ state }: { state: ActionJobEditorState }) {
  const {
    job,
    field,
    index,
    onIndex,
    step,
    stepField,
    change,
    jobId,
    manifest,
    agents,
    defaults,
    defaultModel,
    project,
    workflowKey,
    workflow,
    edits,
    onEdits,
    input,
    suggestions,
    onMove,
  } = state;
  return (
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
                  <ScriptEditor
                    value={step.run ?? ""}
                    shell={step.shell}
                    manifest={manifest}
                    onChange={(value) => stepField("run", value)}
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
                    {["bash", "sh", "pwsh", "powershell", "cmd", "python"].map(
                      (shell) => (
                        <MenuItem value={shell} key={shell}>
                          {shell}
                        </MenuItem>
                      ),
                    )}
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
                    The script runs through the selected shell using an argument
                    vector and the captured job working directory.
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
  );
}
