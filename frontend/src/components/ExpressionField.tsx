import {
  Autocomplete,
  Button,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useState } from "react";
import { expressionDiagnostic } from "../actions-workflow";

export function ExpressionField({
  label,
  value,
  suggestions,
  onChange,
}: {
  label: string;
  value: string;
  suggestions: string[];
  onChange: (value: string) => void;
}) {
  const [choice, setChoice] = useState("");
  const [operator, setOperator] = useState("==");
  const [operand, setOperand] = useState("");
  const diagnostic = value.trim()
    ? expressionDiagnostic(value.replace(/^\s*\$\{\{|\}\}\s*$/g, ""))
    : null;
  const reference = choice.replace(/^\s*\$\{\{|\}\}\s*$/g, "").trim();
  const literal = /^(true|false|null|-?\d+(\.\d+)?)$/.test(operand)
    ? operand
    : `'${operand.replace(/'/g, "''")}'`;
  return (
    <Stack spacing={1}>
      <TextField
        label={label}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        error={Boolean(diagnostic)}
        helperText={
          diagnostic ??
          "Use inputs, upstream outputs, or a status function. The saved workflow is validated by the server."
        }
      />
      <Autocomplete
        freeSolo
        options={suggestions}
        inputValue={choice}
        onInputChange={(_, next) => setChoice(next)}
        renderInput={(parameters) => (
          <TextField
            {...parameters}
            size="small"
            label={`${label} expression helper`}
            helperText="Search a value, then insert it or build a comparison."
          />
        )}
      />
      <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", gap: 1 }}>
        <Button disabled={!choice} onClick={() => onChange(choice)}>
          Insert expression
        </Button>
        <TextField
          select
          size="small"
          label={`${label} operator`}
          value={operator}
          onChange={(event) => setOperator(event.target.value)}
        >
          {["==", "!=", ">", ">=", "<", "<="].map((item) => (
            <MenuItem key={item} value={item}>
              {item}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          size="small"
          label={`${label} comparison value`}
          value={operand}
          onChange={(event) => setOperand(event.target.value)}
        />
        <Button
          disabled={!reference}
          onClick={() =>
            onChange(`\${{ ${reference} ${operator} ${literal} }}`)
          }
        >
          Use comparison
        </Button>
      </Stack>
      <Typography variant="caption" color="text.secondary">
        Example: $&#123;&#123; success() &#125;&#125; runs only after successful
        upstream work. Actual values are resolved from the launch snapshot.
      </Typography>
    </Stack>
  );
}
