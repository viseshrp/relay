import {
  Autocomplete,
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Button,
  Checkbox,
  FormControlLabel,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import type { ActionStep, ActionWorkflow } from "../actions-workflow";
import type { AgentRecord, ProviderDefaults } from "../types";
import type { LanguageManifest } from "../workflow-language";
import { ModelPicker } from "./ModelPicker";
import { AgentConfiguration } from "./AgentConfiguration";
import { MarkdownEditor } from "./MarkdownEditor";
import { PromptFilesEditor, type PromptEdits } from "./PromptFilesEditor";
import { StructuredValueField } from "./StructuredValueField";

export function ActionBuiltinFields({
  step,
  agents,
  defaults,
  defaultModel,
  manifest,
  project,
  workflowKey,
  jobId,
  workflow,
  edits,
  onEdits,
  onChange,
}: {
  step: ActionStep;
  agents: AgentRecord[];
  defaults: Record<string, ProviderDefaults>;
  defaultModel: string;
  manifest: LanguageManifest;
  project: string | null;
  workflowKey: string;
  jobId: string;
  workflow: ActionWorkflow;
  edits: PromptEdits;
  onEdits: (reference: string, edit: PromptEdits[string]) => void;
  onChange: (field: string, value: unknown) => void;
}) {
  const inputs = step.with ?? {};
  const agentId = String(inputs.agent ?? "");
  const agent = agents.find((item) => item.id === agentId);
  const model = String(
    inputs.model ?? defaults[agentId]?.model ?? defaultModel,
  );
  const fields = manifest.builtin_inputs[step.uses ?? ""];
  const special =
    step.uses === "relay/agent@v1"
      ? [
          "agent",
          "agents",
          "model",
          "effort",
          "prompt",
          "prompt-files",
          "auto-retry",
        ]
      : step.uses === "relay/command@v1"
        ? ["argv"]
        : step.uses === "relay/human-wait@v1"
          ? ["options"]
          : [];
  return (
    <Stack spacing={2}>
      {step.uses === "relay/agent@v1" && (
        <>
          <TextField
            select
            label="Agent"
            value={agentId}
            onChange={(event) =>
              onChange("__all__", {
                ...inputs,
                agent: event.target.value || undefined,
                agents: undefined,
                effort: undefined,
              })
            }
          >
            <MenuItem value="">Use saved agent order</MenuItem>
            {agents.map((item) => (
              <MenuItem key={item.id} value={item.id}>
                {item.display_name}
              </MenuItem>
            ))}
          </TextField>
          <ModelPicker
            agents={agent ? [agent] : agents}
            value={String(inputs.model ?? "")}
            project={project}
            defaultLabel={model || "Use saved default"}
            onChange={(value) => {
              onChange("__all__", {
                ...inputs,
                model: value || undefined,
                effort: undefined,
              });
            }}
          />
          {agent && model && !model.includes("${{") && (
            <AgentConfiguration
              agent={agent}
              model={model}
              project={project}
              fields={["effort"]}
              options={
                typeof inputs.effort === "string" || inputs.effort === null
                  ? { effort: inputs.effort }
                  : {}
              }
              onChange={(_, value) =>
                onChange("effort", value === "" ? undefined : value)
              }
            />
          )}
          <Typography component="h3" variant="subtitle1">
            Agent prompt
          </Typography>
          <MarkdownEditor
            label="Agent prompt"
            value={String(inputs.prompt ?? "")}
            onChange={(value) => onChange("prompt", value || undefined)}
          />
          <PromptFilesEditor
            references={String(inputs["prompt-files"] ?? "")}
            workflowKey={workflowKey}
            project={project}
            job={jobId}
            edits={edits}
            onEdits={onEdits}
            onReferences={(value) =>
              onChange("prompt-files", value || undefined)
            }
          />
          <Accordion>
            <AccordionSummary>What the agent receives</AccordionSummary>
            <AccordionDetails>
              <Typography>
                The ordered prompt files above, this step’s inline prompt,
                launch inputs, upstream outputs, and captured run metadata.
              </Typography>
              <Typography sx={{ overflowWrap: "anywhere" }}>
                Inputs:{" "}
                {Object.keys(
                  (workflow.on as { workflow_dispatch?: { inputs?: object } })
                    ?.workflow_dispatch?.inputs ?? {},
                ).join(", ") || "None"}
                . Upstream jobs:{" "}
                {(typeof workflow.jobs[jobId]?.needs === "string"
                  ? [workflow.jobs[jobId]?.needs]
                  : (workflow.jobs[jobId]?.needs ?? [])
                ).join(", ") || "None"}
                .
              </Typography>
            </AccordionDetails>
          </Accordion>
        </>
      )}
      {step.uses === "relay/command@v1" && (
        <StructuredValueField
          label="Program and arguments"
          value={(() => {
            try {
              return JSON.parse(String(inputs.argv ?? '["echo","Ready"]'));
            } catch {
              return [];
            }
          })()}
          onChange={(value) =>
            onChange("__all__", {
              ...inputs,
              command: undefined,
              argv: JSON.stringify(value),
            })
          }
        />
      )}
      {step.uses === "relay/human-wait@v1" && (
        <>
          <Typography>
            Choose a question, optional answer buttons, and a response timeout.
          </Typography>
          <StructuredValueField
            label="Answer buttons"
            value={(() => {
              try {
                return JSON.parse(String(inputs.options ?? "[]"));
              } catch {
                return [];
              }
            })()}
            onChange={(value) =>
              onChange(
                "options",
                Array.isArray(value) && value.length
                  ? JSON.stringify(value)
                  : undefined,
              )
            }
          />
        </>
      )}
      {fields ? (
        fields.allowed
          .filter((field) => !special.includes(field))
          .map((field) => (
            <TextField
              key={field}
              required={fields.required.includes(field)}
              label={`Action ${field}`}
              multiline={[
                "prompt",
                "inputs",
                "options",
                "argv",
                "command",
              ].includes(field)}
              value={String(inputs[field] ?? "")}
              onChange={(event) =>
                onChange(field, event.target.value || undefined)
              }
              helperText={
                field === "workflow"
                  ? "Choose a local reusable workflow, for example ./.relay/workflows/fix.yaml."
                  : field === "options"
                    ? "One answer per line. Free text remains available."
                    : field === "format"
                      ? "exists records a boolean; label, json, or yaml retains a report."
                      : undefined
              }
            />
          ))
      ) : (
        <StructuredValueField
          label="Action inputs"
          object
          value={inputs}
          onChange={(value) => {
            const next = value as Record<string, unknown>;
            onChange("__all__", next);
          }}
        />
      )}
      {step.uses === "relay/agent@v1" && (
        <>
          <Accordion>
            <AccordionSummary>When this job fails</AccordionSummary>
            <AccordionDetails>
              <FormControlLabel
                label="Retry this agent within the saved bounded recovery policy"
                control={
                  <Checkbox
                    checked={
                      inputs["auto-retry"] === true ||
                      inputs["auto-retry"] === "true"
                    }
                    onChange={(event) =>
                      onChange("auto-retry", event.target.checked)
                    }
                  />
                }
              />
              <Typography variant="body2">
                The default stops and tells you. A fix-and-check workflow can
                use a bounded relay/loop step; retries preserve prompts, model,
                and the lifetime retry budget.
              </Typography>
            </AccordionDetails>
          </Accordion>
          <Autocomplete
            multiple
            options={agents.map((item) => item.id)}
            value={(() => {
              try {
                const value = JSON.parse(String(inputs.agents ?? "[]"));
                return Array.isArray(value)
                  ? value.filter(
                      (item): item is string => typeof item === "string",
                    )
                  : [];
              } catch {
                return [];
              }
            })()}
            getOptionLabel={(id) =>
              agents.find((item) => item.id === id)?.display_name ?? id
            }
            onChange={(_, order) =>
              onChange("__all__", {
                ...inputs,
                agent: undefined,
                agents: order.length ? JSON.stringify(order) : undefined,
              })
            }
            renderInput={(parameters) => (
              <TextField
                {...parameters}
                label="Agent order"
                helperText="Ordered exact provider IDs; the first available tool runs."
              />
            )}
          />
        </>
      )}
      {step.uses === "relay/loop@v1" && (
        <Button
          component="a"
          href={`/?view=workflows&workflow=${encodeURIComponent(String(inputs.workflow ?? "").replace(/^\.\/.relay\/workflows\//, ""))}${project ? `&project=${encodeURIComponent(project)}` : ""}`}
        >
          Open loop body
        </Button>
      )}
    </Stack>
  );
}
