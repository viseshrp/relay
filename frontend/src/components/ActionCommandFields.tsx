import { MenuItem, Stack, TextField } from "@mui/material";
import { StructuredValueField } from "./StructuredValueField";
export function ActionCommandFields({
  inputs,
  onChange,
}: {
  inputs: Record<string, unknown>;
  onChange: (field: string, value: unknown) => void;
}) {
  return (
    <Stack spacing={1}>
      <TextField
        select
        label="Command source"
        value={inputs.command !== undefined ? "shared" : "argv"}
        onChange={(event) =>
          onChange(
            "__all__",
            event.target.value === "shared"
              ? { ...inputs, argv: undefined, command: "" }
              : { ...inputs, command: undefined, argv: '["echo","Ready"]' },
          )
        }
      >
        <MenuItem value="argv">Program and arguments</MenuItem>
        <MenuItem value="shared">Shared command</MenuItem>
      </TextField>
      {inputs.command !== undefined ? (
        <TextField
          label="Shared command"
          value={String(inputs.command)}
          onChange={(event) => onChange("command", event.target.value)}
          helperText="The name of a command saved in global or project defaults."
        />
      ) : (
        <StructuredValueField
          label="Program and arguments"
          value={(() => {
            try {
              return JSON.parse(String(inputs.argv ?? '["echo","Ready"]'));
            } catch {
              return [];
            }
          })()}
          onChange={(value) =>
            onChange("__all__", {
              ...inputs,
              command: undefined,
              argv: JSON.stringify(value),
            })
          }
        />
      )}
    </Stack>
  );
}
