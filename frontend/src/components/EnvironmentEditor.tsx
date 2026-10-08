import { HelpField } from "./HelpTip";
import { Alert, Button, Stack, TextField, Typography } from "@mui/material";
import { useState } from "react";

export function EnvironmentEditor({ value, onChange, disabled = false }: {
  value: Record<string, string>; onChange: (value: Record<string, string>) => void; disabled?: boolean;
}) {
  const [error, setError] = useState<string | null>(null);
  function rename(previous: string, next: string) {
    if (next !== previous && Object.hasOwn(value, next)) { setError("That variable name is already in this list."); return; }
    setError(null);
    onChange(Object.fromEntries(Object.entries(value).map(([key, content]) => [key === previous ? next : key, content])));
  }
  return <Stack component="section" aria-label="Environment variables" spacing={1}>
    {error && <Alert severity="error">{error}</Alert>}
    {Object.entries(value).map(([name, content], index) => <Stack component="section" aria-label={`Environment variable ${index + 1}`} key={index} direction="row" spacing={1} useFlexGap sx={{ flexWrap: "wrap", alignItems: "flex-start" }}>
      <HelpField topic="variableName"><TextField fullWidth sx={{ flex: "1 1 220px" }} size="small" label="Variable name" value={name} disabled={disabled} onChange={(event) => rename(name, event.target.value)} /></HelpField>
      <HelpField topic="variableValue"><TextField fullWidth sx={{ flex: "1 1 220px" }} multiline minRows={1} size="small" label="Value" value={content} disabled={disabled} onChange={(event) => onChange({ ...value, [name]: event.target.value })} /></HelpField>
      <Button disabled={disabled} aria-label={`Remove environment variable ${name}`} onClick={() => { setError(null); onChange(Object.fromEntries(Object.entries(value).filter(([key]) => key !== name))); }}>Remove</Button>
    </Stack>)}
    {Object.keys(value).length === 0 && <Typography variant="body2" color="text.secondary">No environment variables declared here.</Typography>}
    <Button disabled={disabled} onClick={() => {
      let index = 1; while (Object.hasOwn(value, `VARIABLE_${index}`)) index += 1;
      onChange({ ...value, [`VARIABLE_${index}`]: "" });
    }}>Add environment variable</Button>
  </Stack>;
}
