import { HelpControl, HelpTextField, HelpSelectField } from "./HelpTip";
import { Alert, Button, Dialog, DialogActions, DialogContent, DialogTitle, FormControlLabel, MenuItem, Stack, Switch, TextField, Typography } from "@mui/material";
import { useCallback, useState } from "react";

import type { AgentsResponse, AgentOptions, RepairDefaults } from "../types";
import type { RepairRuleValue, WorkflowNodeValue } from "../workflow";
import { stageLabel } from "../navigation";
import { AgentConfiguration } from "./AgentConfiguration";
import { ModelPicker } from "./ModelPicker";
import { PromptEditor } from "./PromptEditor";
import { RepairReportSelector } from "./RepairReportSelector";
import { CommandFields } from "./CommandFields";

export function RepairSettings({ stage, sourceOutputs, rule, defaults, agents, commands, model, preferences, project, workflowPath,
  workflowKey, holder, disabled, onChange, onSourceOutput, onClose, onApply, onDirty }: {
  stage: string; rule: RepairRuleValue; defaults: RepairDefaults; agents: AgentsResponse | null;
  commands: Record<string, string[]>;
  model: string; preferences: string[]; project: string | null; workflowPath: string;
  workflowKey: string; holder: string; disabled: boolean;
  onChange: (rule: RepairRuleValue) => void; onClose: () => void; onApply: () => void; onDirty: (dirty: boolean) => void;
  sourceOutputs: Record<string, unknown>;
  onSourceOutput: (output: string, selector: Record<string, unknown>) => void;
}) {
  const [role, setRole] = useState<"fix" | "verify">("fix");
  const [promptDirty, setPromptDirty] = useState(false);
  const handleDirty = useCallback((dirty: boolean) => { setPromptDirty(dirty); onDirty(dirty); }, [onDirty]);
  const node = rule[role];
  const settingsDisabled = disabled || promptDirty || rule.enabled === false;
  const candidates = node.agents?.length ? node.agents : preferences;
  const selectedModel = typeof node.model === "string" ? node.model : "";
  const effectiveModel = selectedModel || model || agents?.defaults?.model
    || agents?.defaults?.providers[candidates[0] ?? ""]?.model || "";
  const resultType = rule.accepted_value === null ? "null" : typeof (rule.accepted_value ?? "Yes");
  // "checks.yaml", stage review, role fix -> "prompts/ui/checks/review-fix.md".
  const promptReference = `prompts/ui/${workflowKey.replace(/\.(yaml|yml)$/, "")}/${stage}-${role}.md`;
  function setNode(value: WorkflowNodeValue) { onChange({ ...rule, [role]: value }); }
  function setOption(agentId: string, field: keyof AgentOptions, value: string | null) {
    const options = { ...node.agent_options };
    const selected = { ...options[agentId] };
    if (value !== "") selected[field] = value; else delete selected[field];
    if (Object.keys(selected).length) options[agentId] = selected; else delete options[agentId];
    setNode({ ...node, agent_options: options });
  }
  function close() { if (!promptDirty) onClose(); }
  return <Dialog open maxWidth="md" fullWidth onClose={close} aria-labelledby="repair-settings-title">
    <DialogTitle id="repair-settings-title">Repairs for {stageLabel(stage)}</DialogTitle>
    <DialogContent><Stack spacing={2} sx={{ pt: 1 }}>
      <Typography>Relay runs the fixer and verifier when this stage rejects its result. Later stages wait for a passing verification. Repair attempts stay in their own panel.</Typography>
      <HelpControl topic="repairs"><FormControlLabel label="Enable automatic repairs" control={<Switch checked={rule.enabled !== false} disabled={disabled || promptDirty} onChange={(event) => onChange({ ...rule, enabled: event.target.checked })} />} /></HelpControl>
      <HelpTextField topic="repairRounds" label="Maximum repair rounds" type="number" value={rule.max_rounds ?? defaults.max_rounds} disabled={settingsDisabled} slotProps={{ htmlInput: { min: 1, max: defaults.max_allowed_rounds } }} onChange={(event) => onChange({ ...rule, max_rounds: Number(event.target.value) })} helperText="Relay stops if no round passes. Restarting the service does not create more rounds." />
      <HelpTextField topic="resultOutput" label="Result output" value={rule.accepted_output} disabled={settingsDisabled} onChange={(event) => onChange({ ...rule, accepted_output: event.target.value })} helperText="The stage and verifier must both declare this output." />
      <RepairReportSelector title="Review report" defaultArtifact="REVIEW.md" value={sourceOutputs[rule.accepted_output]} disabled={settingsDisabled}
        onChange={(selector) => onSourceOutput(rule.accepted_output, selector)} />
      <HelpSelectField topic="resultOutput" label="Result type" size="small" disabled={settingsDisabled} value={resultType} onChange={(event) => onChange({ ...rule, accepted_value: event.target.value === "null" ? null : event.target.value === "boolean" ? true : event.target.value === "number" ? 1 : "Yes" })}>
        <MenuItem value="string">Text</MenuItem><MenuItem value="boolean">True or false</MenuItem><MenuItem value="number">Number</MenuItem>
        <MenuItem value="null">Null</MenuItem>
      </HelpSelectField>
      {typeof rule.accepted_value === "boolean"
        ? <HelpSelectField topic="resultOutput" label="Passing result" size="small" value={String(rule.accepted_value)} disabled={settingsDisabled} onChange={(event) => onChange({ ...rule, accepted_value: event.target.value === "true" })}><MenuItem value="true">True</MenuItem><MenuItem value="false">False</MenuItem></HelpSelectField>
        : rule.accepted_value === null ? <Typography>Passing result: null</Typography>
        : <HelpTextField topic="resultOutput" label="Passing result" value={rule.accepted_value ?? "Yes"} type={typeof rule.accepted_value === "number" ? "number" : "text"} disabled={settingsDisabled} onChange={(event) => onChange({ ...rule, accepted_value: typeof rule.accepted_value === "number" ? Number(event.target.value) : event.target.value })} />}
      <Stack direction="row" spacing={1}>
        {(["fix", "verify"] as const).map((value) => <Button key={value} variant={role === value ? "contained" : "outlined"} disabled={promptDirty} onClick={() => setRole(value)}>{value === "fix" ? "Fixer settings" : "Verifier settings"}</Button>)}
      </Stack>
      <Stack key={role} spacing={2} component="section" aria-label={`${role} settings`}>
        <HelpSelectField topic="stageType" label="Action" size="small" value={node.type} disabled={settingsDisabled} onChange={(event) => setNode({ type: event.target.value, writes: true, allow_no_commit: true, outputs: node.outputs ?? {}, ...(event.target.value === "command" ? { run: ["git", "status"] } : {}) })}><MenuItem value="agent">Agent work</MenuItem><MenuItem value="command">Run a command</MenuItem></HelpSelectField>
        <HelpControl topic="writes"><FormControlLabel label="Allow file changes" control={<Switch checked={node.writes === true} disabled={settingsDisabled} onChange={(event) => setNode({ ...node, writes: event.target.checked })} />} /></HelpControl>
        <HelpControl topic="noCommit"><FormControlLabel label="Allow a completed check without a new commit" control={<Switch checked={node.allow_no_commit === true} disabled={settingsDisabled} onChange={(event) => setNode({ ...node, allow_no_commit: event.target.checked })} />} /></HelpControl>
        {node.type === "agent" && <>
          <HelpSelectField topic="agentOrder" label="Agent tools" size="small" multiple value={node.agents ?? []} disabled={settingsDisabled} onChange={(event) => {
            // MUI's autofill value "codex,claude" represents two tool IDs.
            const value = event.target.value;
            setNode({ ...node, agents: typeof value === "string" ? value.split(",") : value, agent_options: {} });
          }}>
            {agents?.agents.map((agent) => <MenuItem key={agent.id} value={agent.id}>{agent.display_name}</MenuItem>)}
          </HelpSelectField>
          <ModelPicker key={`${role}-${candidates.join(",")}`} agents={agents?.agents.filter((agent) => candidates.includes(agent.id)) ?? []} value={selectedModel} project={project} disabled={settingsDisabled} onChange={(value) => setNode({ ...node, model: value || undefined, agent_options: {} })} />
          {candidates.map((id) => { const agent = agents?.agents.find((item) => item.id === id); return agent ? <AgentConfiguration key={id} agent={agent} model={effectiveModel} inheritDefaults={Boolean(effectiveModel && agents?.defaults?.providers[id]?.model === effectiveModel)} options={node.agent_options?.[id] ?? {}} project={project} disabled={settingsDisabled} onChange={(field, value) => setOption(id, field, value)} /> : null; })}
          <PromptEditor workflowPath={workflowPath} project={project} holder={holder} disabled={disabled || rule.enabled === false}
            reference={node.prompts?.find((prompt) => prompt.local)?.local ?? null}
            newReference={promptReference}
            onDirty={handleDirty}
            onSaved={(reference) => setNode({ ...node, prompts: [...(node.prompts ?? []).filter((prompt) => prompt.local !== reference), { local: reference }] })} />
        </>}
        {node.type === "command" && <CommandFields key={role} node={node} commands={commands} disabled={settingsDisabled} onChange={setNode} />}
        <TextField label={role === "fix" ? "Fixer repair instructions" : "Verifier repair instructions"} multiline minRows={3} disabled={settingsDisabled}
          value={role === "fix" ? rule.fix_instruction ?? defaults.fix_instruction : rule.verify_instruction ?? defaults.verify_instruction}
          onChange={(event) => onChange({ ...rule, [`${role}_instruction`]: event.target.value || undefined })}
          helperText="Appended separately to the frozen agent instructions. You can replace the default." />
        {role === "verify" && <RepairReportSelector title="Verification report" defaultArtifact="REVIEW_FIX_VERIFICATION.md" value={node.outputs?.[rule.accepted_output]} disabled={settingsDisabled}
          onChange={(selector) => setNode({ ...node, outputs: { ...(node.outputs && typeof node.outputs === "object" ? node.outputs : {}), [rule.accepted_output]: selector } })} />}
      </Stack>
      {promptDirty && <Alert severity="warning">Save the instructions before changing repair settings or closing this panel.</Alert>}
    </Stack></DialogContent>
    <DialogActions><Button disabled={promptDirty} onClick={close}>Cancel</Button><Button disabled={disabled || promptDirty} onClick={onApply}>Done</Button></DialogActions>
  </Dialog>;
}
