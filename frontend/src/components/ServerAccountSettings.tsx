import { HelpControl, HelpSelectField, HelpTextField } from "./HelpTip";
import {
  Alert,
  Box,
  FormControlLabel,
  MenuItem,
  Stack,
  Switch,
  Typography,
} from "@mui/material";

import type { SettingsPageState } from "./useSettingsPage";
export function ServerAccountSettings({ state }: { state: SettingsPageState }) {
  const { response, draft, busy, setDraft, fieldErrors } = state;
  return (
    <Stack spacing={3}>
      <Box>
        <Typography variant="h6">Local account</Typography>
        <Typography>
          {response.active_login_required
            ? `Signed in as ${response.username}. Login is currently required.`
            : "Login is disabled. This browser uses local access without signing in."}
        </Typography>
      </Box>
      <HelpControl topic="login" tour>
        <FormControlLabel
          control={
            <Switch
              checked={draft.login_required}
              disabled={busy}
              onChange={(_event, checked) =>
                setDraft({ ...draft, login_required: checked })
              }
            />
          }
          label="Require login"
        />
      </HelpControl>
      <Alert severity="info">
        Restart Relay after changing login, address, port, or workers.
        Command-line flags override saved values for that process. Your existing
        account and data remain saved.
      </Alert>
      <HelpSelectField
        compact
        topic="host"
        tour
        label="Loopback address"
        fullWidth
        value={draft.host}
        disabled={busy}
        onChange={(event) => setDraft({ ...draft, host: event.target.value })}
      >
        {["127.0.0.1", "localhost", "::1"].map((host) => (
          <MenuItem key={host} value={host}>
            {host}
          </MenuItem>
        ))}
      </HelpSelectField>
      <Box className="field-grid server-fields">
        <HelpTextField
          topic="port"
          tour
          label="Port"
          error={Boolean(fieldErrors.port)}
          helperText={fieldErrors.port}
          type="number"
          value={draft.port}
          disabled={busy}
          onChange={(event) =>
            setDraft({ ...draft, port: Number(event.target.value) })
          }
          slotProps={{ htmlInput: { min: 1, max: 65535 } }}
        />
        <HelpTextField
          topic="workers"
          tour
          label="Workers"
          error={Boolean(fieldErrors.workers)}
          type="number"
          value={draft.workers}
          disabled={busy}
          onChange={(event) =>
            setDraft({ ...draft, workers: Number(event.target.value) })
          }
          slotProps={{ htmlInput: { min: 1 } }}
          helperText={
            fieldErrors.workers ??
            "Local jobs that can run at once. Git write locks still apply."
          }
        />
      </Box>
    </Stack>
  );
}
