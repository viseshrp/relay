import { Checkbox, FormControlLabel, Stack, Typography } from "@mui/material";
import { GUIDE, propertyHelp } from "../field-help";
import { isRecord } from "../workflow";
import type { LanguageManifest } from "../workflow-language";
import { HelpControl, HelpTextField } from "./HelpTip";
import { StructuredValueField } from "./StructuredValueField";

export function MatrixEditor({
  value,
  manifest,
  onChange,
}: {
  value: unknown;
  manifest: LanguageManifest;
  onChange: (value: unknown) => void;
}) {
  const help = (key: string, title: string) =>
    propertyHelp(manifest, key, title, GUIDE.matrix);
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
        help={help("strategy.matrix", "Matrix axes")}
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
          help={help(`matrix.${name}`, `Matrix ${name}`)}
          value={matrix[name] ?? []}
          onChange={(next) =>
            onChange({ ...strategy, matrix: { ...matrix, [name]: next } })
          }
        />
      ))}
      <HelpControl
        topic={help(
          "strategy.fail-fast",
          "Stop other matrix jobs when one fails",
        )}
      >
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
      </HelpControl>
      <HelpTextField
        topic={{
          title: "Maximum parallel matrix jobs",
          description:
            "Relay runs matrix jobs one at a time on this computer, so leave this blank.",
          guide: GUIDE.matrix,
        }}
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
