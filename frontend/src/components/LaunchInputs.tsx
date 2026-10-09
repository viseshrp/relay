import { HelpControl, HelpSelectField, HelpTextField } from "./HelpTip";
import { Checkbox, FormControl, FormControlLabel, FormHelperText, MenuItem, Stack } from "@mui/material";

import { stageLabel } from "../navigation";
import type { JsonScalar } from "../types";
import type { InputDefinition } from "../workflow";

export type LaunchValues = Record<string, JsonScalar | undefined>;

export function validateLaunchInputs(definitions: Record<string, InputDefinition>, values: LaunchValues): Record<string, string> {
  const errors: Record<string, string> = {};
  for (const [name, input] of Object.entries(definitions)) {
    const value = values[name] === undefined ? input.default : values[name];
    if (input.required && (value === undefined || value === null || value === "")) errors[name] = "Enter a value for this required input.";
    else if (value !== undefined && value !== null && value !== "") {
      if (["number", "integer"].includes(input.type) && (typeof value !== "number" || !Number.isFinite(value) || (input.type === "integer" && !Number.isInteger(value)))) errors[name] = "Enter a valid number.";
      if (input.type === "boolean" && typeof value !== "boolean") errors[name] = "Choose true or false.";
      if (input.type === "enum" && (!Array.isArray(input.constraints?.values) || !input.constraints.values.includes(value))) errors[name] = "Choose one of the listed values.";
    }
  }
  return errors;
}

function scalar(value: unknown): value is JsonScalar {
  return value === null || typeof value === "string" || typeof value === "number" || typeof value === "boolean";
}

export function LaunchInputs({ definitions, values, onChange, errors = {} }: {
  definitions: Record<string, InputDefinition>;
  values: LaunchValues;
  onChange: (name: string, value: JsonScalar | undefined) => void;
  errors?: Record<string, string>;
}) {
  return <Stack spacing={2}>
    {Object.entries(definitions).map(([name, input]) => {
      const value = values[name] === undefined && scalar(input.default) ? input.default : values[name];
      const label = stageLabel(name);
      if (input.type === "boolean") return <FormControl key={name} required={input.required} error={Boolean(errors[name])}><HelpControl topic="inputs">
        <FormControlLabel label={`${label}${input.required ? " *" : ""}`} control={<Checkbox
          checked={value === true} indeterminate={value === undefined}
          slotProps={{ input: { id: `launch-input-${name}`, "aria-describedby": `launch-help-${name}` } }}
          onChange={(event) => onChange(name, event.target.checked)} />} /></HelpControl>
        {(errors[name] || input.description) && <FormHelperText id={`launch-help-${name}`}>{errors[name] || input.description}</FormHelperText>}
      </FormControl>;
      if (input.type === "enum") {
        const choices = Array.isArray(input.constraints?.values) ? input.constraints.values.filter(scalar) : [];
        return <HelpSelectField key={name} id={`launch-input-${name}`} topic="inputs" label={label} error={Boolean(errors[name])} required={input.required} fullWidth value={value === undefined ? "" : JSON.stringify(value)} helperText={errors[name] || input.description} onChange={(event) => onChange(name, choices.find((choice) => JSON.stringify(choice) === event.target.value))}>
            <MenuItem value="" disabled={input.required === true}>{input.required ? "Select a value" : "Use the default"}</MenuItem>
            {choices.map((choice) => <MenuItem key={JSON.stringify(choice)} value={JSON.stringify(choice)}>{String(choice)}</MenuItem>)}
          </HelpSelectField>;
      }
      const numeric = input.type === "integer" || input.type === "number";
      const long = typeof value === "string" && (value.length > 80 || value.includes("\n"));
      return <HelpTextField key={name} id={`launch-input-${name}`} topic="inputs" label={label} error={Boolean(errors[name])} helperText={errors[name] || input.description} required={input.required} type={numeric ? "number" : "text"} value={value ?? ""} multiline={!numeric} minRows={numeric ? undefined : long ? 3 : 1} maxRows={8} slotProps={{ htmlInput: numeric ? { step: input.type === "integer" ? 1 : "any" } : {} }} onChange={(event) => onChange(name, event.target.value === "" ? (numeric ? null : "") : numeric ? Number(event.target.value) : event.target.value)} />;
    })}
  </Stack>;
}
