import { ScriptEditor } from "./ScriptEditor";
import {
  Button,
  Checkbox,
  FormControlLabel,
  ListItemText,
  MenuItem,
  Stack,
  Typography,
} from "@mui/material";
import { useState } from "react";

import { ActionBuiltinFields } from "./ActionBuiltinFields";
import { actionLabel, actionName, actionType } from "../action-labels";
import { defaultStep } from "../action-defaults";
import { isDeprecatedBuiltin } from "../builtin-actions";
import { propertyHelp, stepHelp } from "../field-help";
import { HelpControl, HelpSelectField, HelpTextField } from "./HelpTip";
import { LoopWorkflowDialog } from "./LoopWorkflowDialog";
import { StepAdvanced, StepList } from "./StepList";
import { groupedTypeOptions, typeReference } from "./StepTypeOptions";

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
    preferences,
    defaults,
    defaultModel,
    project,
    workflowKey,
    workflow,
    edits,
    onEdits,
    input,
    stepSuggestions,
    onMove,
    loopTargets,
    onEditYaml,
    onUpgrade,
    onOpenGetStarted,
  } = state;
  // Where a chosen loop goes: in place of the current step, or at the end.
  const [loop, setLoop] = useState<"replace" | "append" | null>(null);
  const steps = job.steps ?? [];
  const current = Math.min(index, steps.length - 1);
  const uses = step?.uses;
  // An older version keeps its own item, so the select shows what the step runs.
  const older = isDeprecatedBuiltin(manifest, uses);
  const stepType = older
    ? `${actionLabel(uses)} (older version)`
    : actionLabel(uses);
  const help = (property: string, title: string) =>
    stepHelp(manifest, uses, property, title);
  function replaceStep(reference: string, workflow?: string): void {
    change(["jobs", jobId, "steps", index], {
      name: step?.name,
      id: step?.id,
      ...defaultStep(reference, workflow),
    });
  }
  function appendStep(reference: string, workflow?: string): void {
    change(
      ["jobs", jobId, "steps", steps.length],
      defaultStep(reference, workflow),
    );
    onIndex(steps.length);
  }
  return (
    <Stack spacing={2}>
      {job.uses ? (
        <StructuredValueField
          label="Reusable inputs"
          help={propertyHelp(
            manifest,
            "workflow-job.with",
            "Reusable inputs",
            "reusable-workflows-and-local-actions",
          )}
          value={job.with}
          object
          onChange={(value) => field("with", value)}
        />
      ) : (
        <>
          <StepList
            steps={steps}
            current={current}
            manifest={manifest}
            loopAvailable={loopTargets.length > 0}
            onIndex={onIndex}
            onMove={onMove}
            onAdd={(name) => {
              if (name === "loop") setLoop("append");
              else appendStep(typeReference(manifest, name));
            }}
          />
          {step && (
            <>
              <HelpTextField
                topic={help("id", "Step ID")}
                label="Step ID"
                value={step.id ?? ""}
                onChange={(event) =>
                  stepField("id", event.target.value || undefined)
                }
              />
              <HelpTextField
                topic={help("name", "Step name")}
                label="Step name"
                slotProps={{ htmlInput: { maxLength: 256 } }}
                value={step.name ?? ""}
                onChange={(event) =>
                  stepField("name", event.target.value || undefined)
                }
              />
              <HelpSelectField
                topic={propertyHelp(manifest, "regular-step.uses", "Step type")}
                label="Step type"
                width="wide"
                value={older ? step.uses : actionName(step.uses)}
                renderValue={() => stepType}
                onChange={(event) => {
                  const name = String(event.target.value);
                  if (name === step.uses) return;
                  if (name === "loop") setLoop("replace");
                  else replaceStep(typeReference(manifest, name));
                }}
              >
                {groupedTypeOptions(manifest, loopTargets.length > 0)}
                {older && (
                  <MenuItem value={step.uses}>
                    <ListItemText
                      primary={stepType}
                      secondary={actionType(step.uses)?.description}
                    />
                  </MenuItem>
                )}
                {actionName(step.uses) === "local" && (
                  <MenuItem value="local">
                    <ListItemText
                      primary={actionLabel(step.uses)}
                      secondary={actionType(step.uses)?.description}
                    />
                  </MenuItem>
                )}
              </HelpSelectField>
              {step.uses ? (
                <ActionBuiltinFields
                  step={step}
                  agents={agents}
                  preferences={preferences}
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
                  onEditYaml={onEditYaml}
                  onUpgrade={onUpgrade}
                  onOpenGetStarted={onOpenGetStarted}
                />
              ) : (
                <>
                  <ScriptEditor
                    value={step.run ?? ""}
                    shell={step.shell}
                    manifest={manifest}
                    help={help("run", "Script")}
                    onChange={(value) => stepField("run", value)}
                  />
                  <HelpSelectField
                    topic={help("shell", "Shell")}
                    label="Shell"
                    value={step.shell ?? ""}
                    onChange={(event) =>
                      stepField(
                        "shell",
                        String(event.target.value) || undefined,
                      )
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
                  </HelpSelectField>
                  <HelpTextField
                    topic={help("working-directory", "Working directory")}
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
                help={help("if", "Step condition")}
                value={step.if ?? ""}
                suggestions={stepSuggestions}
                onChange={(value) => stepField("if", value || undefined)}
              />
              <HelpTextField
                topic={help(
                  "timeout-minutes",
                  "Timeout (minutes or expression)",
                )}
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
                help={help("env", "Step environment variables")}
                object
                value={step.env}
                onChange={(value) => stepField("env", value)}
              />
              <HelpControl
                topic={help(
                  "continue-on-error",
                  "Continue after this step fails",
                )}
              >
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
              </HelpControl>
              <StepAdvanced
                step={step}
                manifest={manifest}
                onStep={(next) => change(["jobs", jobId, "steps", index], next)}
                onInputs={(value) => input("__all__", value)}
              />
              <Stack direction="row" spacing={1}>
                <Button
                  disabled={index === 0}
                  onClick={() => onMove(index, index - 1)}
                >
                  Move earlier
                </Button>
                <Button
                  disabled={index >= steps.length - 1}
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
          <LoopWorkflowDialog
            open={loop !== null}
            workflows={loopTargets}
            onClose={() => setLoop(null)}
            onChoose={(key) => {
              const reference = typeReference(manifest, "loop");
              if (loop === "replace") replaceStep(reference, key);
              else appendStep(reference, key);
              setLoop(null);
            }}
          />
        </>
      )}
    </Stack>
  );
}
