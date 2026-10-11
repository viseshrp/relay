import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  TextField,
} from "@mui/material";
import { useEffect, useState } from "react";
import { isRecord } from "../workflow";

export function AdvancedJsonField({
  label,
  value,
  object = false,
  onChange,
}: {
  label: string;
  value: unknown;
  object?: boolean;
  onChange: (value: unknown) => void;
}) {
  const serialized = JSON.stringify(value ?? (object ? {} : ""), null, 2);
  const [text, setText] = useState(serialized);
  const [error, setError] = useState("");
  useEffect(() => {
    setText(serialized);
    setError("");
  }, [serialized]);
  return (
    <Accordion>
      <AccordionSummary>Advanced JSON: {label}</AccordionSummary>
      <AccordionDetails>
        <TextField
          label={label}
          multiline
          minRows={3}
          fullWidth
          value={text}
          error={Boolean(error)}
          helperText={
            error ||
            "Edit the same value as JSON. Changes apply when you leave the field."
          }
          onChange={(event) => setText(event.target.value)}
          onBlur={() => {
            try {
              if (!text.trim()) {
                if (value !== undefined) onChange(undefined);
                setError("");
                return;
              }
              const next: unknown = JSON.parse(text);
              if (object && !isRecord(next))
                throw new Error("Enter a JSON object with named values.");
              if (
                JSON.stringify(next) !==
                JSON.stringify(value ?? (object ? {} : ""))
              )
                onChange(next);
              setError("");
            } catch (caught) {
              setError(
                caught instanceof Error ? caught.message : "Enter valid JSON.",
              );
            }
          }}
        />
      </AccordionDetails>
    </Accordion>
  );
}
