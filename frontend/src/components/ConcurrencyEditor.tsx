import { Checkbox, FormControlLabel, Stack } from "@mui/material";
import { GUIDE, propertyHelp } from "../field-help";
import { isRecord } from "../workflow";
import type { LanguageManifest } from "../workflow-language";
import { HelpControl, HelpTextField } from "./HelpTip";

export function ConcurrencyEditor({
  value,
  manifest,
  onChange,
}: {
  value: unknown;
  manifest: LanguageManifest;
  onChange: (value: unknown) => void;
}) {
  const help = (key: string, title: string) =>
    propertyHelp(
      manifest,
      `concurrency-mapping.${key}`,
      title,
      GUIDE.concurrency,
    );
  const settings = isRecord(value)
    ? value
    : { group: typeof value === "string" ? value : "" };
  return (
    <Stack spacing={1}>
      <HelpTextField
        topic={help("group", "Concurrency group")}
        label="Concurrency group"
        value={String(settings.group ?? "")}
        onChange={(event) =>
          onChange({ ...settings, group: event.target.value })
        }
        helperText="Jobs with the same group wait for one another. Expressions are supported."
      />
      <HelpControl
        topic={help(
          "cancel-in-progress",
          "Cancel in-progress work in this group",
        )}
      >
        <FormControlLabel
          label="Cancel in-progress work in this group"
          control={
            <Checkbox
              checked={settings["cancel-in-progress"] === true}
              onChange={(event) =>
                onChange({
                  ...settings,
                  "cancel-in-progress": event.target.checked,
                })
              }
            />
          }
        />
      </HelpControl>
    </Stack>
  );
}
