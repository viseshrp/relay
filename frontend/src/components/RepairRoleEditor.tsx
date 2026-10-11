import { HelpControl, HelpTextField, HelpSelectField } from "./HelpTip";
import { FormControlLabel, MenuItem, Stack, Switch } from "@mui/material";

import { AgentConfiguration } from "./AgentConfiguration";
import { ModelPicker } from "./ModelPicker";
import { PromptEditor } from "./PromptEditor";
import { RepairReportSelector } from "./RepairReportSelector";
import { CommandFields } from "./CommandFields";
import type { RepairSettingsState } from "./useRepairSettings";
export function RepairRoleEditor({ state }: { state: RepairSettingsState }) {
  const {
    role,
    node,
    disabled,
    settingsDisabled,
    onChange,
    setNode,
    agents,
    candidates,
    selectedModel,
    project,
    effectiveModel,
    setOption,
    workflowPath,
    holder,
    rule,
    promptReference,
    handleDirty,
    commands,
    defaults,
  } = state;
  return (
    <Stack
      key={role}
      spacing={2}
      component="section"
      aria-label={`${role} settings`}
    >
      <HelpSelectField
        topic="stageType"
        label="Action"
        size="small"
        value={node.type}
        disabled={settingsDisabled}
        onChange={(event) =>
          setNode({
            type: event.target.value,
            writes: true,
            allow_no_commit: true,
            outputs: node.outputs ?? {},
            ...(event.target.value === "command"
              ? { run: ["git", "status"] }
              : {}),
          })
        }
      >
        <MenuItem value="agent">Agent work</MenuItem>
        <MenuItem value="command">Run a command</MenuItem>
      </HelpSelectField>
      <HelpControl topic="writes">
        <FormControlLabel
          label="Allow file changes"
          control={
            <Switch
              checked={node.writes === true}
              disabled={settingsDisabled}
              onChange={(event) =>
                setNode({ ...node, writes: event.target.checked })
              }
            />
          }
        />
      </HelpControl>
      <HelpControl topic="noCommit">
        <FormControlLabel
          label="Allow a completed check without a new commit"
          control={
            <Switch
              checked={node.allow_no_commit === true}
              disabled={settingsDisabled}
              onChange={(event) =>
                setNode({
                  ...node,
                  allow_no_commit: event.target.checked,
                })
              }
            />
          }
        />
      </HelpControl>
      {node.type === "agent" && (
        <>
          <HelpSelectField
            topic="agentOrder"
            label="Agent tools"
            placeholder="Workflow and owner preferences"
            size="small"
            multiple
            value={node.agents ?? []}
            disabled={settingsDisabled}
            onChange={(event) => {
              // MUI's autofill value "codex,claude" represents two tool IDs.
              const value = event.target.value;
              setNode({
                ...node,
                agents: typeof value === "string" ? value.split(",") : value,
                agent_options: {},
              });
            }}
          >
            {agents?.agents.map((agent) => (
              <MenuItem key={agent.id} value={agent.id}>
                {agent.display_name}
              </MenuItem>
            ))}
          </HelpSelectField>
          <ModelPicker
            key={`${role}-${candidates.join(",")}`}
            agents={
              agents?.agents.filter((agent) => candidates.includes(agent.id)) ??
              []
            }
            value={selectedModel}
            project={project}
            disabled={settingsDisabled}
            onChange={(value) =>
              setNode({
                ...node,
                model: value || undefined,
                agent_options: {},
              })
            }
          />
          {candidates.map((id) => {
            const agent = agents?.agents.find((item) => item.id === id);
            return agent ? (
              <AgentConfiguration
                key={id}
                agent={agent}
                model={effectiveModel}
                inheritDefaults={Boolean(
                  effectiveModel &&
                  agents?.defaults?.providers[id]?.model === effectiveModel,
                )}
                options={node.agent_options?.[id] ?? {}}
                project={project}
                disabled={settingsDisabled}
                onChange={(field, value) => setOption(id, field, value)}
              />
            ) : null;
          })}
          <PromptEditor
            workflowPath={workflowPath}
            project={project}
            holder={holder}
            disabled={disabled || rule.enabled === false}
            reference={
              node.prompts?.find((prompt) => prompt.local)?.local ?? null
            }
            newReference={promptReference}
            onDirty={handleDirty}
            onSaved={(reference) =>
              setNode({
                ...node,
                prompts: [
                  ...(node.prompts ?? []).filter(
                    (prompt) => prompt.local !== reference,
                  ),
                  { local: reference },
                ],
              })
            }
          />
        </>
      )}
      {node.type === "command" && (
        <CommandFields
          key={role}
          node={node}
          commands={commands}
          disabled={settingsDisabled}
          onChange={setNode}
        />
      )}
      <HelpTextField
        topic={role === "fix" ? "fixer" : "verifier"}
        label={
          role === "fix"
            ? "Fixer repair instructions"
            : "Verifier repair instructions"
        }
        multiline
        minRows={3}
        maxRows={8}
        disabled={settingsDisabled}
        value={
          role === "fix"
            ? (rule.fix_instruction ?? defaults.fix_instruction)
            : (rule.verify_instruction ?? defaults.verify_instruction)
        }
        onChange={(event) =>
          onChange({
            ...rule,
            [`${role}_instruction`]: event.target.value || undefined,
          })
        }
        helperText="Appended separately to the frozen agent instructions. You can replace the default."
      />
      {role === "verify" && (
        <RepairReportSelector
          title="Verification report"
          defaultArtifact="REVIEW_FIX_VERIFICATION.md"
          value={node.outputs?.[rule.accepted_output]}
          disabled={settingsDisabled}
          onChange={(selector) =>
            setNode({
              ...node,
              outputs: {
                ...(node.outputs && typeof node.outputs === "object"
                  ? node.outputs
                  : {}),
                [rule.accepted_output]: selector,
              },
            })
          }
        />
      )}
    </Stack>
  );
}
