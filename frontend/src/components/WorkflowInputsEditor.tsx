import { Button, Checkbox, FormControlLabel, MenuItem, Stack, TextField, Typography } from "@mui/material";
import { isRecord } from "../workflow";
import { StructuredValueField } from "./StructuredValueField";

export function WorkflowInputsEditor({ value, onChange }: { value: unknown; onChange: (value: Record<string, unknown>) => void }) {
  const inputs = isRecord(value) ? value : {};
  return <Stack spacing={2}>
    {Object.entries(inputs).map(([name, raw]) => {
      const definition = isRecord(raw) ? raw : {};
      const update = (field: string, entry: unknown) => onChange({ ...inputs, [name]: { ...definition, [field]: entry } });
      return <Stack key={name} spacing={1} component="fieldset" sx={{ border: 0, p: 0 }}>
        <Typography component="legend" variant="subtitle2">Input {name}</Typography>
        <TextField label="Input name" defaultValue={name} onBlur={event => { const next = event.target.value.trim(); if (next && next !== name && !(next in inputs)) onChange(Object.fromEntries(Object.entries(inputs).map(([key, entry]) => [key === name ? next : key, entry]))); }} />
        <TextField select label={`${name} type`} value={definition.type ?? "string"} onChange={event => { const next: Record<string, unknown> = { ...definition, type: event.target.value }; if (event.target.value === "choice") Object.assign(next, { options: ["Option"] }); else delete next.options; delete next.default; onChange({ ...inputs, [name]: next }); }}>{["string", "boolean", "number", "choice", "environment"].map(type => <MenuItem key={type} value={type}>{type}</MenuItem>)}</TextField>
        <FormControlLabel label={`${name} required`} control={<Checkbox checked={definition.required === true} onChange={event => update("required", event.target.checked)} />} />
        <TextField label={`${name} description`} slotProps={{ htmlInput: { maxLength: 4096 } }} value={definition.description ?? ""} onChange={event => update("description", event.target.value)} />
        {definition.type === "choice" && <TextField multiline label={`${name} options (one per line)`} value={Array.isArray(definition.options) ? definition.options.join("\n") : ""} onChange={event => update("options", event.target.value.split("\n"))} />}
        {"default" in definition ? <><StructuredValueField label={`${name} default`} value={definition.default} onChange={entry => update("default", entry)} /><Button onClick={() => { const next = { ...definition }; delete next.default; onChange({ ...inputs, [name]: next }); }}>Remove default</Button></> : <Button onClick={() => update("default", definition.type === "boolean" ? false : definition.type === "number" ? 0 : "")}>Add {name} default</Button>}
        <Button onClick={() => { const next = { ...inputs }; delete next[name]; onChange(next); }}>Remove input {name}</Button>
      </Stack>;
    })}
    <Button onClick={() => { let number = 1; while (`input_${number}` in inputs) number++; onChange({ ...inputs, [`input_${number}`]: { type: "string", required: false, description: "" } }); }}>Add workflow input</Button>
  </Stack>;
}
