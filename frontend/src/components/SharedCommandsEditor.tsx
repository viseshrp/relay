import { Alert, Button, Paper, Stack, TextField, Typography } from "@mui/material";
import { useState } from "react";
import { CommandArgumentsEditor } from "./CommandArgumentsEditor";

export function SharedCommandsEditor({ value, onChange, disabled = false }: {
  value: Record<string, string[]>; onChange: (value: Record<string, string[]>) => void; disabled?: boolean;
}) {
  const [error, setError] = useState<string | null>(null);
  return <Stack component="section" aria-label="Shared commands" spacing={2}>
    {error && <Alert severity="error">{error}</Alert>}
    {Object.entries(value).map(([name, argv], index) => <Paper component="section" aria-label={`Shared command ${index + 1}`} variant="outlined" key={index} sx={{ p: 2 }}><Stack spacing={1}>
      <TextField size="small" label="Command name" value={name} disabled={disabled} helperText="Use a lowercase name such as test, build, or lint." onChange={(event) => {
        const next = event.target.value;
        if (next !== name && Object.hasOwn(value, next)) { setError("That command name is already in this list."); return; }
        setError(null); onChange(Object.fromEntries(Object.entries(value).map(([key, command]) => [key === name ? next : key, command])));
      }} />
      <CommandArgumentsEditor value={argv} disabled={disabled} onChange={(command) => onChange({ ...value, [name]: command })} />
      <Button disabled={disabled} aria-label={`Remove shared command ${name}`} onClick={() => { setError(null); onChange(Object.fromEntries(Object.entries(value).filter(([key]) => key !== name))); }}>Remove command</Button>
    </Stack></Paper>)}
    {Object.keys(value).length === 0 && <Typography variant="body2" color="text.secondary">No shared commands saved.</Typography>}
    <Button disabled={disabled} onClick={() => {
      let index = 1; while (Object.hasOwn(value, `command_${index}`)) index += 1;
      onChange({ ...value, [`command_${index}`]: [""] });
    }}>Add shared command</Button>
  </Stack>;
}
