import { HelpSelectField, HelpControl } from "./HelpTip";
import { FormControlLabel, MenuItem, Stack, Switch, Typography } from "@mui/material";
import type { WorkflowNodeValue } from "../workflow";
import { EnvironmentEditor } from "./EnvironmentEditor";
import { CommandArgumentsEditor } from "./CommandArgumentsEditor";

export function CommandFields({ node, commands, onChange, disabled = false }: {
  node: WorkflowNodeValue; commands: Record<string, string[]>; onChange: (node: WorkflowNodeValue) => void; disabled?: boolean;
}) {
  const shared = node.run && !Array.isArray(node.run) ? node.run.command : null;
  const argv = Array.isArray(node.run) ? node.run : [];
  return <Stack spacing={1}>
    <HelpSelectField topic="commands" label="Command source" fullWidth size="small" value={shared === null ? "custom" : "shared"} disabled={disabled} onChange={(event) => {
      onChange({ ...node, run: event.target.value === "shared" ? { command: "" } : [""] });
    }}><MenuItem value="custom">Program and arguments</MenuItem><MenuItem value="shared">Shared command from Settings</MenuItem></HelpSelectField>
    {shared !== null ? <>
      <HelpSelectField topic="commands" label="Shared command" fullWidth size="small" value={shared} disabled={disabled} onChange={(event) => onChange({ ...node, run: { command: event.target.value } })}>
        {shared && !Object.hasOwn(commands, shared) && <MenuItem value={shared}>{shared} (not configured)</MenuItem>}
        {Object.keys(commands).map((name) => <MenuItem value={name} key={name}>{name}</MenuItem>)}
      </HelpSelectField>
      <Typography variant="body2" color="text.secondary">{shared && commands[shared] ? JSON.stringify(commands[shared]) : "Choose a named command saved in Global defaults or Project defaults. Missing commands stop launch."}</Typography>
    </> : <CommandArgumentsEditor value={argv} disabled={disabled} onChange={(run) => onChange({ ...node, run })} />}
    <HelpControl topic="environment"><FormControlLabel label="Use inherited environment variables" control={<Switch checked={node.inherit_env !== false} disabled={disabled} onChange={(_event, checked) => onChange({ ...node, inherit_env: checked })} />} /></HelpControl>
    <Typography variant="body2" color="text.secondary">Job variables override workflow, project, and global values. Turn inheritance off to keep only this job's declared variables alongside the worker environment.</Typography>
    <EnvironmentEditor value={node.env ?? {}} disabled={disabled} onChange={(env) => onChange({ ...node, env })} />
  </Stack>;
}
