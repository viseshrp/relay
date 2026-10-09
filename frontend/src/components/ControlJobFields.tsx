import { HelpTextField, HelpSelectField } from "./HelpTip";
import { Button, MenuItem, Stack, Typography } from "@mui/material";
import { stageLabel } from "../navigation";
import type { WorkflowNodeValue } from "../workflow";

export function ControlJobFields({ node, targets, onChange }: {
  node: WorkflowNodeValue; targets: string[]; onChange: (node: WorkflowNodeValue) => void;
}) {
  if (node.type === "condition") {
    const branches = Object.entries(node.branches ?? {});
    return <Stack spacing={2} className="control-job-fields">
      <HelpTextField topic="expression" label="Expression" size="small" value={typeof node.expr === "string" ? node.expr : ""} onChange={(event) => onChange({ ...node, expr: event.target.value })} />
      <Typography variant="subtitle2">Result branches</Typography>
      {branches.map(([value, target], index) => <Stack key={index} className="condition-branch" direction="row" spacing={1} useFlexGap sx={{ flexWrap: "wrap", alignItems: "flex-start" }}>
        <HelpTextField topic="expression" label="Result value" size="small" value={value} onChange={(event) => onChange({ ...node, branches: Object.fromEntries(branches.map(([key, destination], position) => [position === index ? event.target.value : key, destination])) })} />
        <HelpSelectField topic="dependencies" label="Next job" size="small" sx={{ minWidth: 180 }} value={target} onChange={(event) => onChange({ ...node, branches: { ...node.branches, [value]: event.target.value } })}>
          {targets.map((id) => <MenuItem key={id} value={id}>{stageLabel(id)}</MenuItem>)}
          {!targets.includes(target) && <MenuItem value={target}>{target || "Choose a job"}</MenuItem>}
        </HelpSelectField>
        <Button aria-label={`Remove branch ${value}`} onClick={() => onChange({ ...node, branches: Object.fromEntries(branches.filter((_branch, position) => position !== index)) })}>Remove</Button>
      </Stack>)}
      <Button sx={{ alignSelf: "flex-start" }} onClick={() => {
        let number = branches.length + 1;
        while (node.branches?.[`result_${number}`] !== undefined) number += 1;
        onChange({ ...node, branches: { ...node.branches, [`result_${number}`]: targets[0] ?? "" } });
      }}>Add result branch</Button>
    </Stack>;
  }
  if (node.type === "loop") return <Stack spacing={2} className="control-job-fields">
    <HelpTextField topic="loop" label="Maximum iterations" size="small" type="number" value={node.max_iterations ?? 1} slotProps={{ htmlInput: { min: 1 } }} onChange={(event) => onChange({ ...node, max_iterations: Number(event.target.value) })} />
    <HelpTextField topic="expression" label="Stop repeating when" size="small" value={node.until ?? ""} onChange={(event) => onChange({ ...node, until: event.target.value || undefined })} />
    <HelpSelectField topic="loop" label="Job after exhausted iterations" placeholder="Choose a job" size="small" value={node.exhausted ?? ""} onChange={(event) => onChange({ ...node, exhausted: event.target.value })}>
      {targets.map((id) => <MenuItem key={id} value={id}>{stageLabel(id)}</MenuItem>)}
      {node.exhausted && !targets.includes(node.exhausted) && <MenuItem value={node.exhausted}>{node.exhausted}</MenuItem>}
    </HelpSelectField>
    <Typography variant="body2">Loop jobs: {Object.keys(node.body ?? {}).map(stageLabel).join(", ") || "None"}. Edit their definitions in YAML.</Typography>
  </Stack>;
  return null;
}
