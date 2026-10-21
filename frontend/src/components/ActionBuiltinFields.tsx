import { BuiltinInputFields } from "./BuiltinInputFields";
import { ActionCommandFields } from "./ActionCommandFields";
import { ReusableWorkflowPreview } from "./ReusableWorkflowPreview";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Button,
  Stack,
  Typography,
} from "@mui/material";
import { actionLabel } from "../action-labels";
import type { ActionStep, ActionWorkflow } from "../actions-workflow";
import type { AgentRecord, ProviderDefaults } from "../types";
import { isDeprecatedBuiltin, parseBuiltin } from "../builtin-actions";
import { inputHelp, propertyHelp } from "../field-help";
import { parseListInput } from "../list-input";
import type { LanguageManifest } from "../workflow-language";
import { ModelPicker } from "./ModelPicker";
import { AgentConfiguration } from "./AgentConfiguration";
import { AgentRouteField } from "./AgentRouteField";
import { HelpLabel } from "./HelpTip";
import { MarkdownEditor } from "./MarkdownEditor";
import { PromptFilesEditor, type PromptEdits } from "./PromptFilesEditor";
import { StructuredValueField } from "./StructuredValueField";

export function ActionBuiltinFields({
  step,
  agents,
  preferences,
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
  onEditYaml,
  onUpgrade,
  onOpenGetStarted,
}: {
  step: ActionStep;
  agents: AgentRecord[];
  preferences: string[];
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
  onEditYaml: () => void;
  /** Move the workflow's deprecated steps to the current version. */
  onUpgrade?: () => void;
  onOpenGetStarted?: () => void;
}) {
  const inputs = step.with ?? {};
  const action = parseBuiltin(step.uses)?.name;
  const agentId = String(inputs.agent ?? "");
  const agent = agents.find((item) => item.id === agentId);
  const model = String(
    inputs.model ?? defaults[agentId]?.model ?? defaultModel,
  );
  const fields = manifest.builtin_inputs[step.uses ?? ""];
  const help = (input: string, title: string) =>
    inputHelp(manifest, step.uses, input, title);
  const special =
    action === "agent"
      ? [
          "agent",
          "agents",
          "model",
          "effort",
          "prompt",
          "prompt-files",
          "auto-retry",
          "retry-limit",
        ]
      : action === "command"
        ? ["argv", "command"]
        : action === "human-wait"
          ? ["options"]
          : [];
  return (
    <Stack spacing={2}>
      {isDeprecatedBuiltin(manifest, step.uses) && (
        <Alert
          severity="info"
          action={
            onUpgrade ? (
              <Button onClick={onUpgrade}>Update to current versions</Button>
            ) : undefined
          }
        >
          This step uses an older version of {actionLabel(step.uses)}.
        </Alert>
      )}
      {action === "agent" && (
        <>
          <AgentRouteField
            inputs={inputs}
            agents={agents}
            preferences={preferences}
            help={help("agents", "Runs on")}
            agentHelp={help("agent", "Agent")}
            orderHelp={help("agents", "Add an agent")}
            onChange={(next) => onChange("__all__", next)}
            onEditYaml={onEditYaml}
            onOpenGetStarted={onOpenGetStarted}
          />
          <ModelPicker
            agents={agent ? [agent] : agents}
            value={String(inputs.model ?? "")}
            project={project}
            help={help("model", "Model")}
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
              inheritDefaults
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
            <HelpLabel topic={help("prompt", "Agent prompt")}>
              Agent prompt
            </HelpLabel>
          </Typography>
          <MarkdownEditor
            label="Agent prompt"
            value={String(inputs.prompt ?? "")}
            onChange={(value) => onChange("prompt", value || undefined)}
          />
          <PromptFilesEditor
            help={help("prompt-files", "Ordered prompt files")}
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
      {action === "command" && (
        <ActionCommandFields
          inputs={inputs}
          reference={step.uses}
          manifest={manifest}
          onChange={onChange}
        />
      )}
      {action === "human-wait" && (
        <>
          <Typography>
            Choose a question, optional answer buttons, and a response timeout.
          </Typography>
          <StructuredValueField
            label="Answer buttons"
            help={help("options", "Answer buttons")}
            textItems
            value={parseListInput(inputs.options) ?? []}
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
        <BuiltinInputFields
          fields={fields}
          special={special}
          inputs={inputs}
          help={help}
          onChange={onChange}
        />
      ) : (
        <StructuredValueField
          label="Action inputs"
          help={propertyHelp(
            manifest,
            "regular-step.with",
            "Action inputs",
            "reusable-workflows-and-local-actions",
          )}
          advanced={false}
          object
          value={inputs}
          onChange={(value) => {
            const next = value as Record<string, unknown>;
            onChange("__all__", next);
          }}
        />
      )}
      {action === "loop" && Boolean(inputs.workflow) && (
        <ReusableWorkflowPreview
          reference={String(inputs.workflow)}
          project={project}
          loop
        />
      )}
    </Stack>
  );
}
