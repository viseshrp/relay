import { Checkbox, FormControlLabel, Stack, TextField } from "@mui/material";
import { isRecord } from "../workflow";

export function ConcurrencyEditor({
  value,
  onChange,
}: {
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const settings = isRecord(value)
    ? value
    : { group: typeof value === "string" ? value : "" };
  return (
    <Stack spacing={1}>
      <TextField
        label="Concurrency group"
        value={String(settings.group ?? "")}
        onChange={(event) =>
          onChange({ ...settings, group: event.target.value })
        }
        helperText="Jobs with the same group wait for one another. Expressions are supported."
      />
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
    </Stack>
  );
}
