import { FormControl, InputLabel, MenuItem, Select, Stack, TextField, Typography } from "@mui/material";
import { useId } from "react";
import { isRecord } from "../workflow";

function record(value: unknown): Record<string, unknown> {
  return isRecord(value) ? value : {};
}

export function RepairReportSelector({ title, value, defaultArtifact, disabled, onChange }: {
  title: string; value: unknown; defaultArtifact: string; disabled: boolean;
  onChange: (selector: Record<string, unknown>) => void;
}) {
  const id = useId();
  const selector = record(value);
  const kind = ["label", "json_path", "yaml_path", "exists"].find((key) => key in selector) ?? "label";
  const fields = record(selector[kind]);
  const artifact = typeof fields.artifact === "string" ? fields.artifact : typeof selector.exists === "string" ? selector.exists : defaultArtifact;
  const key = kind === "label" ? "label" : "path";
  const location = typeof fields[key] === "string" ? fields[key] : kind === "label" ? "Ready" : "ready";
  function update(type: string, file: string, field: string) {
    onChange(type === "exists" ? { exists: file } : { [type]: { artifact: file, [type === "label" ? "label" : "path"]: field } });
  }
  return <Stack spacing={1} component="section" aria-label={title}>
    <Typography variant="subtitle2">{title}</Typography>
    <FormControl size="small"><InputLabel id={id}>{title} format</InputLabel><Select labelId={id} label={`${title} format`} value={kind} disabled={disabled} onChange={(event) => update(event.target.value, artifact, event.target.value === "label" ? "Ready" : "ready")}>
      <MenuItem value="label">Labeled text</MenuItem><MenuItem value="json_path">JSON field</MenuItem><MenuItem value="yaml_path">YAML field</MenuItem><MenuItem value="exists">File exists</MenuItem>
    </Select></FormControl>
    <TextField label={`${title} file`} value={artifact} disabled={disabled} onChange={(event) => update(kind, event.target.value, location)} />
    {kind !== "exists" && <TextField label={kind === "label" ? `${title} label` : `${title} field path`} value={location} disabled={disabled} onChange={(event) => update(kind, artifact, event.target.value)}
      helperText={kind === "label" ? "Ready: Yes returns the text Yes." : "result.ready reads the ready field inside result."} />}
    {kind === "exists" && <Typography variant="body2" color="warning.main">File existence gives a boolean without retaining the report. Use a labeled result or data field to keep rejection evidence.</Typography>}
  </Stack>;
}
