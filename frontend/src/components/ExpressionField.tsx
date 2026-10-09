import { Button, MenuItem, Stack, TextField } from "@mui/material";
import { useState } from "react";
import { expressionDiagnostic } from "../actions-workflow";

export function ExpressionField({ label, value, suggestions, onChange }: { label: string; value: string; suggestions: string[]; onChange: (value: string) => void }) {
  const [choice, setChoice] = useState("");
  const diagnostic = value.trim() ? expressionDiagnostic(value.replace(/^\s*\$\{\{|\}\}\s*$/g, "")) : null;
  return <Stack spacing={1}><TextField label={label} value={value} onChange={event => onChange(event.target.value)} error={Boolean(diagnostic)} helperText={diagnostic ?? "Use inputs, upstream outputs, or a status function."} />
    <Stack direction="row" spacing={1}><TextField select size="small" label={`${label} expression helper`} value={choice} onChange={event => setChoice(event.target.value)} sx={{ flex: 1 }}>{suggestions.map(item => <MenuItem key={item} value={item}>{item}</MenuItem>)}</TextField><Button disabled={!choice} onClick={() => onChange(choice)}>Insert expression</Button></Stack>
  </Stack>;
}
