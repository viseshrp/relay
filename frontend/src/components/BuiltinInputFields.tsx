import { TextField } from "@mui/material";
import { StructuredValueField } from "./StructuredValueField";

export function BuiltinInputFields({
  fields,
  special,
  inputs,
  onChange,
}: {
  fields: { allowed: string[]; required: string[] };
  special: string[];
  inputs: Record<string, unknown>;
  onChange: (field: string, value: unknown) => void;
}) {
  return fields.allowed
    .filter((field) => !special.includes(field))
    .map((field) => {
      if (field === "inputs" && !String(inputs[field] ?? "").includes("${{")) {
        let values: unknown = {};
        try {
          values = JSON.parse(String(inputs[field] ?? "{}"));
        } catch {
          // The advanced action input editor retains invalid source for correction.
        }
        return (
          <StructuredValueField
            key={field}
            label="Workflow input values"
            object
            value={values}
            onChange={(value) => onChange(field, JSON.stringify(value))}
          />
        );
      }
      return (
        <TextField
          key={field}
          required={fields.required.includes(field)}
          label={
            field === "inputs" ? "Workflow input expression" : `Action ${field}`
          }
          multiline={["prompt", "options", "command"].includes(field)}
          value={String(inputs[field] ?? "")}
          onChange={(event) => onChange(field, event.target.value || undefined)}
          helperText={
            field === "workflow"
              ? "Choose a local reusable workflow, for example ./.relay/workflows/fix.yaml."
              : field === "format"
                ? "exists records a boolean; label, json, or yaml retains a report."
                : undefined
          }
        />
      );
    });
}
