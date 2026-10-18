import { Alert, MenuItem, Stack } from "@mui/material";
import { inputHelp } from "../field-help";
import { parseListInput } from "../list-input";
import type { LanguageManifest } from "../workflow-language";
import { HelpSelectField, HelpTextField } from "./HelpTip";
import { StructuredValueField } from "./StructuredValueField";

export function ActionCommandFields({
  inputs,
  reference,
  manifest,
  onChange,
}: {
  inputs: Record<string, unknown>;
  reference: string | undefined;
  manifest: LanguageManifest;
  onChange: (field: string, value: unknown) => void;
}) {
  // Show exactly what the YAML holds: nothing when argv is absent, and an
  // error rather than an empty list when it cannot be read.
  const argv = inputs.argv === undefined ? [] : parseListInput(inputs.argv);
  return (
    <Stack spacing={1}>
      <HelpSelectField
        topic={{
          title: "Command source",
          description:
            "Program and arguments runs the argv input exactly. Shared command runs a command saved by name in global or project defaults.",
          guide: "scripts-and-command-actions",
        }}
        label="Command source"
        size="small"
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
      </HelpSelectField>
      {inputs.command !== undefined ? (
        <HelpTextField
          topic={inputHelp(manifest, reference, "command", "Shared command")}
          label="Shared command"
          value={String(inputs.command)}
          onChange={(event) => onChange("command", event.target.value)}
          helperText="The name of a command saved in global or project defaults."
        />
      ) : (
        <>
          {argv === null && (
            <Alert severity="error">
              This argument list is not valid. Fix it in YAML or replace it
              here.
            </Alert>
          )}
          <StructuredValueField
            label="Program and arguments"
            help={inputHelp(
              manifest,
              reference,
              "argv",
              "Program and arguments",
            )}
            textItems
            value={argv ?? []}
            helperText={
              inputs.argv === undefined
                ? "Add the program, then one argument per item."
                : undefined
            }
            onChange={(value) =>
              onChange("__all__", {
                ...inputs,
                command: undefined,
                argv: JSON.stringify(value),
              })
            }
          />
        </>
      )}
    </Stack>
  );
}
