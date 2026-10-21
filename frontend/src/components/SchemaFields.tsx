import { Button, MenuItem, Stack, Typography } from "@mui/material";
import { useState } from "react";
import { propertyHelp } from "../field-help";
import type { LanguageManifest } from "../workflow-language";
import { HelpSelectField } from "./HelpTip";
import { schemaKind } from "../workflow-language";
import { isRecord } from "../workflow";
import { StructuredValueField } from "./StructuredValueField";

export function SchemaFields({
  manifest,
  type,
  value,
  onChange,
  omit = [],
  label = "",
}: {
  manifest: LanguageManifest;
  type: string;
  value: unknown;
  onChange: (key: string, value: unknown) => void;
  omit?: string[];
  label?: string;
}) {
  const [add, setAdd] = useState("");
  const record = isRecord(value) ? value : {};
  const properties = manifest.definitions[type]?.mapping?.properties ?? {};
  const missing = Object.keys(properties).filter(
    (key) => !omit.includes(key) && !(key in record),
  );
  return (
    <Stack spacing={2}>
      {Object.entries(properties)
        .filter(([key]) => !omit.includes(key) && key in record)
        .map(([key, descriptor]) => {
          const fieldType =
            typeof descriptor === "string" ? descriptor : descriptor.type;
          const definition = manifest.definitions[fieldType];
          return (
            <Stack key={key} spacing={1}>
              <StructuredValueField
                label={label ? `${label}.${key}` : key}
                help={propertyHelp(
                  manifest,
                  `${type}.${key}`,
                  label ? `${label}.${key}` : key,
                )}
                value={record[key]}
                onChange={(next) => onChange(key, next)}
                object={
                  schemaKind(fieldType, manifest.definitions, record[key]) ===
                    "table" && !definition?.["one-of"]
                }
              />
              {definition?.description && (
                <Typography variant="body2" color="text.secondary">
                  {definition.description}
                </Typography>
              )}
              <Button
                size="small"
                sx={{ alignSelf: "start" }}
                onClick={() => onChange(key, undefined)}
              >
                Remove {label ? `${label}.` : ""}
                {key}
              </Button>
            </Stack>
          );
        })}
      {missing.length > 0 && (
        <Stack direction="row" spacing={1} sx={{ alignItems: "end" }}>
          <HelpSelectField
            topic={{
              title: label ? `Add ${label} field` : "Add workflow field",
              description:
                "Fields this part of the workflow also accepts. Choose one, then Add field to edit its value here.",
            }}
            label={label ? `Add ${label} field` : "Add workflow field"}
            size="small"
            value={add}
            placeholder="Choose a field"
            onChange={(event) => setAdd(String(event.target.value))}
          >
            {missing.map((key) => (
              <MenuItem key={key} value={key}>
                {key}
              </MenuItem>
            ))}
          </HelpSelectField>
          <Button
            disabled={!add}
            onClick={() => {
              const descriptor = properties[add];
              const type =
                typeof descriptor === "string" ? descriptor : descriptor.type;
              const kind = schemaKind(type, manifest.definitions);
              onChange(
                add,
                (
                  {
                    table: {},
                    list: [],
                    boolean: false,
                    number: 1,
                    text: "",
                  } as Record<string, unknown>
                )[kind],
              );
              setAdd("");
            }}
          >
            Add field
          </Button>
        </Stack>
      )}
    </Stack>
  );
}
