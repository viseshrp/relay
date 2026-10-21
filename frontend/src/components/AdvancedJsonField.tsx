import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  TextField,
  type TextFieldProps,
} from "@mui/material";
import { useEffect, useState } from "react";
import { isRecord } from "../workflow";
import { HelpTextField, type HelpSource } from "./HelpTip";

export function AdvancedJsonField({
  label,
  value,
  object = false,
  onChange,
  help,
}: {
  label: string;
  value: unknown;
  object?: boolean;
  onChange: (value: unknown) => void;
  help?: HelpSource;
}) {
  const serialized = JSON.stringify(value ?? (object ? {} : ""), null, 2);
  const [text, setText] = useState(serialized);
  const [error, setError] = useState("");
  useEffect(() => {
    setText(serialized);
    setError("");
  }, [serialized]);
  const field: TextFieldProps & { label: string } = {
    label,
    multiline: true,
    minRows: 3,
    fullWidth: true,
    value: text,
    error: Boolean(error),
    helperText:
      error ||
      "Edit the same value as JSON. Changes apply when you leave the field.",
    onChange: (event) => setText(event.target.value),
    onBlur: () => {
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
          JSON.stringify(next) !== JSON.stringify(value ?? (object ? {} : ""))
        )
          onChange(next);
        setError("");
      } catch (caught) {
        setError(
          caught instanceof Error ? caught.message : "Enter valid JSON.",
        );
      }
    },
  };
  return (
    <Accordion>
      <AccordionSummary>Advanced JSON: {label}</AccordionSummary>
      <AccordionDetails>
        {/* With help, the label sits beside a help button like other fields. */}
        {help ? (
          <HelpTextField topic={help} {...field} />
        ) : (
          <TextField {...field} />
        )}
      </AccordionDetails>
    </Accordion>
  );
}
