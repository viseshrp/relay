import {
  Button,
  Checkbox,
  FormControlLabel,
  MenuItem,
  Stack,
  Typography,
} from "@mui/material";
import { GUIDE } from "../field-help";
import { isRecord } from "../workflow";
import type { LanguageManifest } from "../workflow-language";
import {
  HelpControl,
  HelpSelectField,
  HelpTextField,
  type HelpSource,
} from "./HelpTip";
import { StructuredValueField } from "./StructuredValueField";

export function WorkflowInputsEditor({
  value,
  manifest,
  onChange,
}: {
  value: unknown;
  manifest: LanguageManifest | null;
  onChange: (value: Record<string, unknown>) => void;
}) {
  const inputs = isRecord(value) ? value : {};
  const help = (property: string | null, title: string): HelpSource => ({
    title,
    description:
      (property &&
        manifest?.property_descriptions[
          `workflow-dispatch-input.${property}`
        ]) ||
      "The name a run's launch form shows and expressions read as inputs.<name>. Use letters, digits, _, or -.",
    guide: GUIDE.inputs,
  });
  return (
    <Stack spacing={2}>
      {Object.entries(inputs).map(([name, raw]) => {
        const definition = isRecord(raw) ? raw : {};
        const update = (field: string, entry: unknown) =>
          onChange({ ...inputs, [name]: { ...definition, [field]: entry } });
        return (
          <Stack key={name} spacing={2} sx={{ border: 0, p: 0, mt: 2 }}>
            <Typography variant="subtitle2" sx={{ fontWeight: 600, mb: 1.5 }}>
              Input {name}
            </Typography>
            <HelpTextField
              topic={help(null, "Input name")}
              label="Input name"
              margin="dense"
              sx={{ mt: 0.5 }}
              defaultValue={name}
              onBlur={(event) => {
                const next = event.target.value.trim();
                if (next && next !== name && !(next in inputs))
                  onChange(
                    Object.fromEntries(
                      Object.entries(inputs).map(([key, entry]) => [
                        key === name ? next : key,
                        entry,
                      ]),
                    ),
                  );
              }}
            />
            <HelpSelectField
              topic={help("type", `${name} type`)}
              label={`${name} type`}
              value={String(definition.type ?? "string")}
              onChange={(event) => {
                const next: Record<string, unknown> = {
                  ...definition,
                  type: event.target.value,
                };
                if (event.target.value === "choice")
                  Object.assign(next, { options: ["Option"] });
                else delete next.options;
                delete next.default;
                onChange({ ...inputs, [name]: next });
              }}
            >
              {["string", "boolean", "number", "choice", "environment"].map(
                (type) => (
                  <MenuItem key={type} value={type}>
                    {type}
                  </MenuItem>
                ),
              )}
            </HelpSelectField>
            <HelpControl topic={help("required", `${name} required`)}>
              <FormControlLabel
                label={`${name} required`}
                control={
                  <Checkbox
                    checked={definition.required === true}
                    onChange={(event) =>
                      update("required", event.target.checked)
                    }
                  />
                }
              />
            </HelpControl>
            <HelpTextField
              topic={help("description", `${name} description`)}
              width="wide"
              label={`${name} description`}
              slotProps={{ htmlInput: { maxLength: 4096 } }}
              value={definition.description ?? ""}
              onChange={(event) => update("description", event.target.value)}
            />
            {definition.type === "choice" && (
              <HelpTextField
                topic={help("options", `${name} options (one per line)`)}
                multiline
                label={`${name} options (one per line)`}
                value={
                  Array.isArray(definition.options)
                    ? definition.options.join("\n")
                    : ""
                }
                onChange={(event) =>
                  update("options", event.target.value.split("\n"))
                }
              />
            )}
            {"default" in definition ? (
              <>
                <StructuredValueField
                  label={`${name} default`}
                  help={help("default", `${name} default`)}
                  value={definition.default}
                  onChange={(entry) => update("default", entry)}
                />
                <Button
                  onClick={() => {
                    const next = { ...definition };
                    delete next.default;
                    onChange({ ...inputs, [name]: next });
                  }}
                >
                  Remove default
                </Button>
              </>
            ) : (
              <Button
                onClick={() =>
                  update(
                    "default",
                    definition.type === "boolean"
                      ? false
                      : definition.type === "number"
                        ? 0
                        : "",
                  )
                }
              >
                Add {name} default
              </Button>
            )}
            <Button
              onClick={() => {
                const next = { ...inputs };
                delete next[name];
                onChange(next);
              }}
            >
              Remove input {name}
            </Button>
          </Stack>
        );
      })}
      <Button
        onClick={() => {
          let number = 1;
          while (`input_${number}` in inputs) number++;
          onChange({
            ...inputs,
            [`input_${number}`]: {
              type: "string",
              required: false,
              description: "",
            },
          });
        }}
      >
        Add workflow input
      </Button>
    </Stack>
  );
}
