import { ActionIcon } from "./ActionIcon";
import { HelpTextField } from "./HelpTip";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Stack,
  TextField,
} from "@mui/material";
import { useState } from "react";

export function CommandArgumentsEditor({
  value,
  onChange,
  disabled = false,
}: {
  value: string[];
  onChange: (value: string[]) => void;
  disabled?: boolean;
}) {
  const [error, setError] = useState<string | null>(null);
  return (
    <Stack spacing={1}>
      {error && <Alert severity="error">{error}</Alert>}
      <HelpTextField
        topic="program"
        label="Program"
        size="small"
        value={value[0] ?? ""}
        disabled={disabled}
        onChange={(event) => onChange([event.target.value, ...value.slice(1)])}
      />
      <HelpTextField
        topic="arguments"
        label="Arguments (one per line)"
        size="small"
        multiline
        minRows={2}
        maxRows={8}
        value={value.slice(1).join("\n")}
        disabled={disabled}
        onChange={(event) =>
          onChange([
            value[0] ?? "",
            ...(event.target.value === ""
              ? []
              : event.target.value.split("\n")),
          ])
        }
        helperText="Each line is passed as one argument. Spaces are kept; shell syntax is not expanded."
      />
      <Accordion>
        <AccordionSummary expandIcon={<ActionIcon name="down" />}>
          Advanced command arguments
        </AccordionSummary>
        <AccordionDetails>
          <TextField
            key={JSON.stringify(value)}
            fullWidth
            multiline
            minRows={2}
            maxRows={8}
            size="small"
            label="Argument vector as JSON"
            defaultValue={JSON.stringify(value)}
            disabled={disabled}
            helperText="Use JSON to preserve empty arguments or newlines inside an argument."
            onBlur={(event) => {
              try {
                const parsed: unknown = JSON.parse(event.target.value);
                if (
                  !Array.isArray(parsed) ||
                  !parsed.every((item: unknown) => typeof item === "string")
                ) {
                  setError("Command arguments must be a JSON string array.");
                  return;
                }
                const strings = parsed.filter(
                  (item: unknown): item is string => typeof item === "string",
                );
                setError(null);
                onChange(strings);
              } catch {
                setError("Command arguments must be a JSON string array.");
              }
            }}
          />
        </AccordionDetails>
      </Accordion>
    </Stack>
  );
}
