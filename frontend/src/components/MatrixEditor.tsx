import {
  Checkbox,
  FormControlLabel,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { isRecord } from "../workflow";
import { StructuredValueField } from "./StructuredValueField";

export function MatrixEditor({
  value,
  onChange,
}: {
  value: unknown;
  onChange: (value: unknown) => void;
}) {
  const strategy = isRecord(value) ? value : {};
  const matrix = isRecord(strategy.matrix) ? strategy.matrix : {};
  const axes = Object.fromEntries(
    Object.entries(matrix).filter(
      ([name]) => !["include", "exclude"].includes(name),
    ),
  );
  return (
    <Stack spacing={2}>
      <Typography>
        Each combination of axis values creates a job. Add axes and lists of
        values below.
      </Typography>
      <StructuredValueField
        label="Matrix axes"
        object
        value={axes}
        onChange={(next) =>
          onChange({
            ...strategy,
            matrix: {
              ...(isRecord(next) ? next : {}),
              ...(matrix.include !== undefined
                ? { include: matrix.include }
                : {}),
              ...(matrix.exclude !== undefined
                ? { exclude: matrix.exclude }
                : {}),
            },
          })
        }
      />
      {(["include", "exclude"] as const).map((name) => (
        <StructuredValueField
          key={name}
          label={`Matrix ${name}`}
          value={matrix[name] ?? []}
          onChange={(next) =>
            onChange({ ...strategy, matrix: { ...matrix, [name]: next } })
          }
        />
      ))}
      <FormControlLabel
        label="Stop other matrix jobs when one fails"
        control={
          <Checkbox
            checked={strategy["fail-fast"] !== false}
            onChange={(event) =>
              onChange({ ...strategy, "fail-fast": event.target.checked })
            }
          />
        }
      />
      <TextField
        label="Maximum parallel matrix jobs"
        type="number"
        slotProps={{ htmlInput: { min: 1 } }}
        value={String(strategy["max-parallel"] ?? "")}
        onChange={(event) =>
          onChange({
            ...strategy,
            "max-parallel": event.target.value
              ? Number(event.target.value)
              : undefined,
          })
        }
      />
    </Stack>
  );
}
