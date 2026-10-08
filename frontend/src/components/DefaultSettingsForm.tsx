import { ActionIcon } from "./ActionIcon";
import { HelpField, HelpLabel } from "./HelpTip";
import { Accordion, AccordionDetails, AccordionSummary, Alert, Box, Button, FormControl, FormControlLabel, FormHelperText, InputLabel, MenuItem, Select, Stack, Switch, TextField, Typography } from "@mui/material";
import { useId, useState } from "react";
import type { AgentOptions, AgentRecord, OwnerSettings, ProjectDefaultOverrides, ProviderDefaults, WorkflowDefaults } from "../types";
import { AgentConfiguration } from "./AgentConfiguration";
import { ModelPicker } from "./ModelPicker";
import { EnvironmentEditor } from "./EnvironmentEditor";
import { SharedCommandsEditor } from "./SharedCommandsEditor";

interface Props {
  settings: OwnerSettings;
  agents: AgentRecord[];
  onChange: (settings: OwnerSettings) => void;
  project: string | null;
  disabled: boolean;
  overrides?: ProjectDefaultOverrides;
  onOverrides?: (values: ProjectDefaultOverrides) => void;
  tourActive?: boolean;
}

const overrideLabels: Record<keyof WorkflowDefaults | "agent_preferences" | "cleanup_policy", string> = {
  agent_preferences: "agent order", cleanup_policy: "working-copy cleanup", model: "shared model",
  providers: "agent models and thinking", timeout: "job timeout", auto_retry: "automatic job retries",
  recovery: "automatic recovery", repairs: "new repair rules",
  commands: "shared commands", env: "environment variables",
};

export function DefaultSettingsForm({ settings, agents, onChange, project, disabled, overrides, onOverrides, tourActive = false }: Props) {
  const prefix = useId();
  const [repairOpen, setRepairOpen] = useState(false);
  const defaults = settings.workflow_defaults;
  const projectMode = overrides !== undefined;
  function update<K extends keyof WorkflowDefaults>(key: K, value: WorkflowDefaults[K]) {
    onChange({ ...settings, workflow_defaults: { ...defaults, [key]: value } });
    onOverrides?.({ ...overrides, workflow_defaults: { ...overrides?.workflow_defaults, [key]: value } });
  }
  function ownerUpdate<K extends "agent_preferences" | "cleanup_policy">(key: K, value: OwnerSettings[K]) {
    onChange({ ...settings, [key]: value });
    onOverrides?.({ ...overrides, [key]: value });
  }
  function inherit(key: keyof WorkflowDefaults | "agent_preferences" | "cleanup_policy") {
    if (!onOverrides || !overrides) return null;
    const root = key === "agent_preferences" || key === "cleanup_policy";
    const selected = Object.hasOwn(root ? overrides : overrides.workflow_defaults ?? {}, key);
    return <HelpField topic="override"><FormControlLabel control={<Switch size="small" checked={selected} disabled={disabled} onChange={(_event, checked) => {
      const next = { ...overrides, workflow_defaults: { ...overrides.workflow_defaults } };
      if (root) {
        if (checked) Object.assign(next, { [key]: settings[key] });
        else delete next[key];
      } else if (checked) Object.assign(next.workflow_defaults, { [key]: defaults[key] });
      else delete next.workflow_defaults[key];
      onOverrides(next);
    }} />} label={`Override ${overrideLabels[key]} for this project`} /></HelpField>;
  }
  function locked(key: keyof WorkflowDefaults | "agent_preferences" | "cleanup_policy") {
    return disabled || (projectMode && !Object.hasOwn(key === "agent_preferences" || key === "cleanup_policy" ? overrides : overrides.workflow_defaults ?? {}, key));
  }
  function providerChange(id: string, value: ProviderDefaults) { update("providers", { ...defaults.providers, [id]: value }); }
  return <Stack spacing={3}>
    <Box data-tour="agentOrder" className="settings-group"><Typography variant="h6"><HelpLabel topic="agentOrder">Default agent order</HelpLabel></Typography>
      <Typography color="text.secondary" variant="body2">Job and workflow tools come first. Relay checks the same exact model in this order.</Typography>
      {inherit("agent_preferences")}
      <Stack spacing={1} sx={{ mt: 1 }}>
        {settings.agent_preferences.map((id, index) => <Stack key={id} direction="row" spacing={1} useFlexGap sx={{ alignItems: "center", flexWrap: "wrap" }}>
          <Typography sx={{ flex: 1 }}>{index + 1}. {agents.find((agent) => agent.id === id)?.display_name ?? id}</Typography>
          <Button size="small" disabled={locked("agent_preferences") || index === 0} aria-label={`Move ${id} up`} onClick={() => {
            const order = [...settings.agent_preferences]; [order[index - 1], order[index]] = [order[index], order[index - 1]]; ownerUpdate("agent_preferences", order);
          }}>Move up</Button>
          <Button size="small" disabled={locked("agent_preferences")} aria-label={`Remove ${id} from default order`} onClick={() => ownerUpdate("agent_preferences", settings.agent_preferences.filter((value) => value !== id))}>Remove</Button>
        </Stack>)}
        {settings.agent_preferences.length === 0 && <Typography variant="body2">No global agent order. Workflows must choose their tools.</Typography>}
        <FormControl size="small"><InputLabel id={`${prefix}-agent`}>Add an agent</InputLabel>
          <Select labelId={`${prefix}-agent`} label="Add an agent" value="" disabled={locked("agent_preferences")} onChange={(event) => ownerUpdate("agent_preferences", [...settings.agent_preferences, event.target.value])}>
            {agents.filter((agent) => !settings.agent_preferences.includes(agent.id)).map((agent) => <MenuItem key={agent.id} value={agent.id}>{agent.display_name}{agent.installed ? "" : " (not installed)"}</MenuItem>)}
          </Select>
        </FormControl>
      </Stack>
    </Box>
    <Box>{inherit("model")}<HelpField topic="sharedModel" tour><TextField fullWidth label="Shared default model" value={defaults.model ?? ""} disabled={locked("model")} onChange={(event) => update("model", event.target.value || null)} helperText="Optional exact value. Used when the job, run, and workflow have no model. Leave blank to use the first preferred agent's model below." /></HelpField></Box>
    <Box data-tour="providers" className="settings-group"><Typography variant="h6"><HelpLabel topic="providers">Agent models and thinking</HelpLabel></Typography>
      <Typography color="text.secondary" variant="body2" sx={{ mb: 1 }}>Thinking effort and permissions apply only when the exact model matches. Saved workflow choices take precedence. Unsupported choices stop preflight.</Typography>
      {inherit("providers")}
      {agents.map((agent) => {
        const value = defaults.providers[agent.id] ?? { model: null };
        const options: AgentOptions = { effort: value.effort ?? undefined, permission_mode: value.permission_mode ?? undefined };
        return <Accordion key={agent.id} disableGutters slotProps={{ transition: { unmountOnExit: true } }}><AccordionSummary expandIcon={<ActionIcon name="down" />}><Stack direction={{ xs: "column", sm: "row" }} spacing={1} sx={{ width: "100%", minWidth: 0, justifyContent: "space-between" }}><Typography>{agent.display_name}</Typography><Typography color="text.secondary" variant="body2" sx={{ overflowWrap: "anywhere", minWidth: 0 }}>{value.model ?? "No saved model"}</Typography></Stack></AccordionSummary>
          <AccordionDetails><Stack spacing={2}>
            <ModelPicker defaultLabel="No saved model" agents={[agent]} value={value.model ?? ""} project={project} disabled={locked("providers")} onChange={(model) => providerChange(agent.id, { model: model || null, effort: null, permission_mode: null })} />
            <HelpField topic="model"><TextField label={`${agent.display_name} exact model`} value={value.model ?? ""} disabled={locked("providers")} onChange={(event) => providerChange(agent.id, { model: event.target.value || null, effort: null, permission_mode: null })} helperText="Model values preserve case. Changing the model clears its saved effort and permissions." /></HelpField>
            <AgentConfiguration agent={agent} model={value.model ?? ""} options={options} project={project} disabled={locked("providers")} labels={{ effort: "Thinking effort", permission_mode: "What the agent may do" }} defaultLabel="Agent’s default" onChange={(field, selected) => providerChange(agent.id, { ...value, [field]: selected || null })} />
            {value.permission_mode && <Alert severity="info">New jobs using this exact model inherit this permission choice unless the workflow sets its own. Review the agent's description before saving.</Alert>}
          </Stack></AccordionDetails></Accordion>;
      })}
    </Box>
    <Box data-tour="commands" className="settings-group"><Typography variant="h6"><HelpLabel topic="commands">Shared commands</HelpLabel></Typography>
      <Typography variant="body2" color="text.secondary">Save named programs and arguments for command jobs to select. Each run captures the selected command. Existing program and argument lists stay explicit.</Typography>
      {inherit("commands")}
      <SharedCommandsEditor value={defaults.commands} disabled={locked("commands")} onChange={(commands) => update("commands", commands)} />
    </Box>
    <Box data-tour="environment" className="settings-group"><Typography variant="h6"><HelpLabel topic="environment">Environment variables</HelpLabel></Typography>
      <Typography variant="body2" color="text.secondary">Defaults for command jobs. Workflow and job variables take precedence. Values are stored locally and captured in runs; output is not masked.</Typography>
      {inherit("env")}
      <EnvironmentEditor value={defaults.env} disabled={locked("env")} onChange={(env) => update("env", env)} />
    </Box>
    <Box><Typography variant="h6">Job defaults</Typography><Stack spacing={2} sx={{ mt: 2 }}>
      <Box>{inherit("timeout")}<HelpField topic="timeout" tour><TextField fullWidth label="Job timeout" value={defaults.timeout ?? ""} disabled={locked("timeout")} onChange={(event) => update("timeout", event.target.value || null)} helperText="For agent and command jobs without a timeout. Use 30s, 15m, or 2h. Blank leaves the workflow and agent limits in place. Human approvals keep their declared deadline." /></HelpField></Box>
      <Box data-tour="autoRetry">{inherit("auto_retry")}<HelpField topic="autoRetry"><FormControlLabel control={<Switch checked={defaults.auto_retry} disabled={locked("auto_retry")} onChange={(_event, checked) => update("auto_retry", checked)} />} label="Allow automatic retries for jobs" /></HelpField><Typography variant="body2" color="text.secondary">Requires an enabled recovery policy. Each job can opt out.</Typography></Box>
      <Box>{inherit("recovery")}<HelpField topic="recovery" tour><FormControlLabel control={<Switch checked={defaults.recovery.enabled} disabled={locked("recovery")} onChange={(_event, checked) => update("recovery", { ...defaults.recovery, enabled: checked })} />} label="Automatic recovery for new runs" /></HelpField><Box sx={{ height: 16 }} />
        <HelpField topic="retryLimit" tour><TextField fullWidth type="number" label="Maximum automatic retries" value={defaults.recovery.max_retries} disabled={locked("recovery")} onChange={(event) => update("recovery", { ...defaults.recovery, max_retries: Number(event.target.value) })} slotProps={{ htmlInput: { min: 1, max: 2 } }} helperText="One or two additional attempts per failed agent job. Models, permissions, and completed work stay captured." /></HelpField></Box>
      <Box>{inherit("cleanup_policy")}<HelpField topic="cleanup" tour><FormControl fullWidth><InputLabel id={`${prefix}-cleanup`}>After a successful run</InputLabel><Select labelId={`${prefix}-cleanup`} label="After a successful run" value={settings.cleanup_policy} disabled={locked("cleanup_policy")} onChange={(event) => ownerUpdate("cleanup_policy", event.target.value === "merge_on_success" ? "merge_on_success" : event.target.value === "retain" ? "retain" : "clean_on_success")}><MenuItem value="clean_on_success">Delete the working copy</MenuItem><MenuItem value="retain">Keep the working copy</MenuItem><MenuItem value="merge_on_success">Merge into the active branch, then delete working copies</MenuItem></Select><FormHelperText>{settings.cleanup_policy === "merge_on_success" ? "Fast-forwards the branch selected at launch. The checkout must be completely clean at launch and completion. Dirty, switched, or diverged branches fail and keep the run working copy." : "Reports, commits, and history remain available. Run workflow can override this choice."}</FormHelperText></FormControl></HelpField></Box>
    </Stack></Box>
    <HelpField topic="repairs" tour><Accordion expanded={tourActive || repairOpen} onChange={(_event, expanded) => setRepairOpen(expanded)}><AccordionSummary expandIcon={<ActionIcon name="down" />}>Defaults for new repair rules</AccordionSummary><AccordionDetails><Stack spacing={2}>
      <Typography variant="body2">Used when adding a repair rule in the editor. Saved repair rules keep their rounds and instructions.</Typography>
      {inherit("repairs")}
      <HelpField topic="repairRounds" tour><TextField label="Maximum repair rounds" type="number" value={defaults.repairs.max_rounds} disabled={locked("repairs")} onChange={(event) => update("repairs", { ...defaults.repairs, max_rounds: Number(event.target.value) })} slotProps={{ htmlInput: { min: 1, max: 100 } }} /></HelpField>
      <HelpField topic="fixer" tour><TextField label="Fixer instructions" multiline minRows={3} value={defaults.repairs.fix_instruction} disabled={locked("repairs")} onChange={(event) => update("repairs", { ...defaults.repairs, fix_instruction: event.target.value })} /></HelpField>
      <HelpField topic="verifier" tour><TextField label="Verifier instructions" multiline minRows={3} value={defaults.repairs.verify_instruction} disabled={locked("repairs")} onChange={(event) => update("repairs", { ...defaults.repairs, verify_instruction: event.target.value })} /></HelpField>
    </Stack></AccordionDetails></Accordion></HelpField>
  </Stack>;
}
