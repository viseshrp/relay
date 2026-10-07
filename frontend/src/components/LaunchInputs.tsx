import { Checkbox, FormControl, FormControlLabel, FormHelperText, InputLabel, MenuItem, Select, Stack, TextField } from "@mui/material";

import { stageLabel } from "../navigation";
import type { JsonScalar } from "../types";
import type { InputDefinition } from "../workflow";

export type LaunchValues = Record<string, JsonScalar | undefined>;

function scalar(value: unknown): value is JsonScalar {
  return value === null || typeof value === "string" || typeof value === "number" || typeof value === "boolean";
}

export function LaunchInputs({ definitions, values, onChange }: {
  definitions: Record<string, InputDefinition>;
  values: LaunchValues;
  onChange: (name: string, value: JsonScalar | undefined) => void;
}) {
  return <Stack spacing={2}>
    {Object.entries(definitions).map(([name, input]) => {
      const value = values[name] === undefined && scalar(input.default) ? input.default : values[name];
      const label = stageLabel(name);
      if (input.type === "boolean") return <FormControl key={name} required={input.required}>
        <FormControlLabel label={`${label}${input.required ? " *" : ""}`} control={<Checkbox
          checked={value === true} indeterminate={value === undefined}
          slotProps={{ input: { "aria-describedby": input.description ? `launch-help-${name}` : undefined } }}
          onChange={(event) => onChange(name, event.target.checked)} />} />
        {input.description && <FormHelperText id={`launch-help-${name}`}>{input.description}</FormHelperText>}
      </FormControl>;
      if (input.type === "enum") {
        const choices = Array.isArray(input.constraints?.values) ? input.constraints.values.filter(scalar) : [];
        return <FormControl key={name} required={input.required} fullWidth>
          <InputLabel id={`launch-input-${name}`}>{label}</InputLabel>
          <Select labelId={`launch-input-${name}`} label={label} value={value === undefined ? "" : JSON.stringify(value)}
            inputProps={{ "aria-describedby": input.description ? `launch-help-${name}` : undefined }}
            onChange={(event) => onChange(name, choices.find((choice) => JSON.stringify(choice) === event.target.value))}>
            <MenuItem value="" disabled={input.required === true}>{input.required ? "Select a value" : "Use the default"}</MenuItem>
            {choices.map((choice) => <MenuItem key={JSON.stringify(choice)} value={JSON.stringify(choice)}>{String(choice)}</MenuItem>)}
          </Select>
          {input.description && <FormHelperText id={`launch-help-${name}`}>{input.description}</FormHelperText>}
        </FormControl>;
      }
      const numeric = input.type === "integer" || input.type === "number";
      const long = typeof value === "string" && (value.length > 80 || value.includes("\n"));
      return <TextField key={name} label={label} helperText={input.description} required={input.required}
        type={numeric ? "number" : "text"} value={value ?? ""} multiline={!numeric} minRows={numeric ? undefined : long ? 3 : 1} maxRows={8}
        slotProps={{ htmlInput: numeric ? { step: input.type === "integer" ? 1 : "any" } : {} }}
        onChange={(event) => onChange(name, event.target.value === "" ? (numeric ? null : "") : numeric ? Number(event.target.value) : event.target.value)} />;
    })}
  </Stack>;
}
