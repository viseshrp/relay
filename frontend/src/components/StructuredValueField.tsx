import {
  Alert,
  Box,
  Button,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useState } from "react";
import { isRecord } from "../workflow";
import { AdvancedJsonField } from "./AdvancedJsonField";

export function StructuredValueField({
  label,
  value,
  onChange,
  object = false,
  advanced = true,
}: {
  label: string;
  value: unknown;
  onChange: (value: unknown) => void;
  object?: boolean;
  advanced?: boolean;
}) {
  const [error, setError] = useState("");
  const kind = isRecord(value)
    ? "table"
    : Array.isArray(value)
      ? "list"
      : typeof value === "boolean"
        ? "boolean"
        : typeof value === "number"
          ? "number"
          : "text";
  const record = isRecord(value) ? value : {};
  function add() {
    let index = 1;
    while (`key_${index}` in record) index++;
    onChange({ ...record, [`key_${index}`]: "" });
  }
  return (
    <Stack
      spacing={1}
      component="fieldset"
      sx={{ minWidth: 0, border: 0, p: 0, m: 0 }}
    >
      <Typography component="legend" variant="subtitle2">
        {label}
      </Typography>
      {!object && (
        <TextField
          select
          size="small"
          label={`${label} value type`}
          value={kind}
          onChange={(event) =>
            onChange(
              (
                {
                  text: "",
                  number: 0,
                  boolean: false,
                  table: {},
                  list: [],
                } as Record<string, unknown>
              )[event.target.value],
            )
          }
        >
          {[
            ["text", "Text or expression"],
            ["number", "Number"],
            ["boolean", "Boolean"],
            ["table", "Key/value table"],
            ["list", "List"],
          ].map(([id, name]) => (
            <MenuItem key={id} value={id}>
              {name}
            </MenuItem>
          ))}
        </TextField>
      )}
      {kind === "table" || object ? (
        <>
          {Object.entries(record).map(([key, entry]) => (
            <Box key={key} className="structured-row">
              <TextField
                label={`${label} key`}
                defaultValue={key}
                size="small"
                onBlur={(event) => {
                  const next = event.target.value.trim();
                  if (!next || next === key) return;
                  if (next in record) {
                    setError("This name is already used.");
                    return;
                  }
                  const renamed = Object.fromEntries(
                    Object.entries(record).map(([name, item]) => [
                      name === key ? next : name,
                      item,
                    ]),
                  );
                  setError("");
                  onChange(renamed);
                }}
              />
              <StructuredValueField
                advanced={false}
                label={`${label}.${key}`}
                value={entry}
                onChange={(next) => onChange({ ...record, [key]: next })}
              />
              <Button
                size="small"
                aria-label={`Remove ${label}.${key}`}
                onClick={() => {
                  const next = { ...record };
                  delete next[key];
                  onChange(next);
                }}
              >
                Remove
              </Button>
            </Box>
          ))}
          <Button sx={{ alignSelf: "start" }} onClick={add}>
            Add {label} entry
          </Button>
        </>
      ) : kind === "list" ? (
        <>
          {(value as unknown[]).map((entry, index) => (
            <Stack key={index} direction="row" spacing={1}>
              <StructuredValueField
                advanced={false}
                label={`${label} item ${index + 1}`}
                value={entry}
                onChange={(next) =>
                  onChange(
                    (value as unknown[]).map((item, offset) =>
                      offset === index ? next : item,
                    ),
                  )
                }
              />
              <Button
                aria-label={`Remove ${label} item ${index + 1}`}
                onClick={() =>
                  onChange(
                    (value as unknown[]).filter(
                      (_, offset) => offset !== index,
                    ),
                  )
                }
              >
                Remove
              </Button>
            </Stack>
          ))}
          <Button onClick={() => onChange([...(value as unknown[]), ""])}>
            Add {label} item
          </Button>
        </>
      ) : kind === "boolean" ? (
        <TextField
          select
          label={label}
          value={String(value)}
          onChange={(event) => onChange(event.target.value === "true")}
        >
          <MenuItem value="true">True</MenuItem>
          <MenuItem value="false">False</MenuItem>
        </TextField>
      ) : (
        <TextField
          label={label}
          multiline={kind === "text"}
          size="small"
          value={value == null ? "" : String(value)}
          type={kind === "number" ? "number" : "text"}
          onChange={(event) =>
            onChange(
              kind === "number"
                ? Number(event.target.value)
                : event.target.value,
            )
          }
        />
      )}
      {error && <Alert severity="error">{error}</Alert>}
      {advanced && (
        <AdvancedJsonField
          label={label}
          value={value}
          object={object}
          onChange={onChange}
        />
      )}
    </Stack>
  );
}
