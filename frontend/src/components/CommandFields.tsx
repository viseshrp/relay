import { FormControl, FormControlLabel, InputLabel, MenuItem, Select, Stack, Switch, Typography } from "@mui/material";
import { useId } from "react";
import type { WorkflowNodeValue } from "../workflow";
import { EnvironmentEditor } from "./EnvironmentEditor";
import { CommandArgumentsEditor } from "./CommandArgumentsEditor";

export function CommandFields({ node, commands, onChange, disabled = false }: {
  node: WorkflowNodeValue; commands: Record<string, string[]>; onChange: (node: WorkflowNodeValue) => void; disabled?: boolean;
}) {
  const prefix = useId();
  const shared = node.run && !Array.isArray(node.run) ? node.run.command : null;
  const argv = Array.isArray(node.run) ? node.run : [];
  return <Stack spacing={1}>
    <FormControl size="small"><InputLabel id={`${prefix}-source`}>Command source</InputLabel><Select labelId={`${prefix}-source`} label="Command source" value={shared === null ? "custom" : "shared"} disabled={disabled} onChange={(event) => {
      onChange({ ...node, run: event.target.value === "shared" ? { command: "" } : [""] });
    }}><MenuItem value="custom">Program and arguments</MenuItem><MenuItem value="shared">Shared command from Settings</MenuItem></Select></FormControl>
    {shared !== null ? <>
      <FormControl size="small"><InputLabel id={`${prefix}-command`}>Shared command</InputLabel><Select labelId={`${prefix}-command`} label="Shared command" value={shared} disabled={disabled} onChange={(event) => onChange({ ...node, run: { command: event.target.value } })}>
        {shared && !Object.hasOwn(commands, shared) && <MenuItem value={shared}>{shared} (not configured)</MenuItem>}
        {Object.keys(commands).map((name) => <MenuItem value={name} key={name}>{name}</MenuItem>)}
      </Select></FormControl>
      <Typography variant="body2" color="text.secondary">{shared && commands[shared] ? JSON.stringify(commands[shared]) : "Choose a named command saved in Global defaults or Project defaults. Missing commands stop launch."}</Typography>
    </> : <CommandArgumentsEditor value={argv} disabled={disabled} onChange={(run) => onChange({ ...node, run })} />}
    <FormControlLabel label="Use inherited environment variables" control={<Switch checked={node.inherit_env !== false} disabled={disabled} onChange={(_event, checked) => onChange({ ...node, inherit_env: checked })} />} />
    <Typography variant="body2" color="text.secondary">Job variables override workflow, project, and global values. Turn inheritance off to keep only this job's declared variables alongside the worker environment.</Typography>
    <EnvironmentEditor value={node.env ?? {}} disabled={disabled} onChange={(env) => onChange({ ...node, env })} />
  </Stack>;
}
