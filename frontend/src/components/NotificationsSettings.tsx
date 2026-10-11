import { HelpControl } from "./HelpTip";
import { FormControlLabel, Stack, Switch, Typography } from "@mui/material";

import type { SettingsPageState } from "./useSettingsPage";
export function NotificationsSettings({ state }: { state: SettingsPageState }) {
  const { notifications, onToggleNotifications } = state;
  return (
    <Stack spacing={2}>
      <Typography>
        Notifications cover waiting runs and completed runs across every project
        in this browser. They contain no questions or agent output.
      </Typography>
      <HelpControl topic="notifications" tour>
        <FormControlLabel
          control={
            <Switch
              checked={notifications}
              onChange={() => void onToggleNotifications()}
            />
          }
          label="Desktop notifications"
        />
      </HelpControl>
      <Typography variant="body2" color="text.secondary">
        Enabling notifications asks this browser for permission. Other browsers
        keep their own preference.
      </Typography>
    </Stack>
  );
}
