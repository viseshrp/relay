import { Button, FormControl, InputLabel, MenuItem, Select, Stack, TextField, Typography } from "@mui/material";
import { stageLabel } from "../navigation";
import type { WorkflowNodeValue } from "../workflow";

export function ControlJobFields({ node, targets, onChange }: {
  node: WorkflowNodeValue; targets: string[]; onChange: (node: WorkflowNodeValue) => void;
}) {
  if (node.type === "condition") {
    const branches = Object.entries(node.branches ?? {});
    return <Stack spacing={2}>
      <TextField size="small" label="Expression" value={typeof node.expr === "string" ? node.expr : ""} onChange={(event) => onChange({ ...node, expr: event.target.value })} />
      <Typography variant="subtitle2">Result branches</Typography>
      {branches.map(([value, target], index) => <Stack key={index} direction="row" spacing={1}>
        <TextField size="small" label="Result value" value={value} onChange={(event) => onChange({ ...node, branches: Object.fromEntries(branches.map(([key, destination], position) => [position === index ? event.target.value : key, destination])) })} />
        <FormControl size="small" sx={{ minWidth: 180 }}><InputLabel id={`branch-target-${index}`}>Next job</InputLabel><Select labelId={`branch-target-${index}`} label="Next job" value={target} onChange={(event) => onChange({ ...node, branches: { ...node.branches, [value]: event.target.value } })}>
          {targets.map((id) => <MenuItem key={id} value={id}>{stageLabel(id)}</MenuItem>)}
          {!targets.includes(target) && <MenuItem value={target}>{target || "Choose a job"}</MenuItem>}
        </Select></FormControl>
        <Button aria-label={`Remove branch ${value}`} onClick={() => onChange({ ...node, branches: Object.fromEntries(branches.filter((_branch, position) => position !== index)) })}>Remove</Button>
      </Stack>)}
      <Button onClick={() => {
        let number = branches.length + 1;
        while (node.branches?.[`result_${number}`] !== undefined) number += 1;
        onChange({ ...node, branches: { ...node.branches, [`result_${number}`]: targets[0] ?? "" } });
      }}>Add result branch</Button>
    </Stack>;
  }
  if (node.type === "loop") return <Stack spacing={2}>
    <TextField size="small" type="number" label="Maximum iterations" value={node.max_iterations ?? 1} slotProps={{ htmlInput: { min: 1 } }} onChange={(event) => onChange({ ...node, max_iterations: Number(event.target.value) })} />
    <TextField size="small" label="Stop repeating when" value={node.until ?? ""} onChange={(event) => onChange({ ...node, until: event.target.value || undefined })} />
    <FormControl size="small"><InputLabel id="loop-exhausted">Job after exhausted iterations</InputLabel><Select labelId="loop-exhausted" label="Job after exhausted iterations" value={node.exhausted ?? ""} onChange={(event) => onChange({ ...node, exhausted: event.target.value })}>
      {targets.map((id) => <MenuItem key={id} value={id}>{stageLabel(id)}</MenuItem>)}
      {node.exhausted && !targets.includes(node.exhausted) && <MenuItem value={node.exhausted}>{node.exhausted}</MenuItem>}
    </Select></FormControl>
    <Typography variant="body2">Loop jobs: {Object.keys(node.body ?? {}).map(stageLabel).join(", ") || "None"}. Edit their definitions in YAML.</Typography>
  </Stack>;
  return null;
}
