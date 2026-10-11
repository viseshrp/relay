import { HelpControl, HelpTextField, HelpSelectField } from "./HelpTip";
import {
  Box,
  FormControlLabel,
  MenuItem,
  Stack,
  Switch,
  Typography,
} from "@mui/material";

import type { DefaultSettingsFormState } from "./useDefaultSettingsForm";
export function DefaultRecoverySettings({
  state,
}: {
  state: DefaultSettingsFormState;
}) {
  const { inherit, errors, defaults, locked, update, settings, ownerUpdate } =
    state;
  return (
    <Box>
      <Typography variant="h6">Job defaults</Typography>
      <Stack spacing={2} sx={{ mt: 2 }}>
        <Box>
          {inherit("timeout")}
          <HelpTextField
            compact
            topic="timeout"
            tour
            label="Job timeout"
            error={Boolean(errors.timeout)}
            fullWidth
            value={defaults.timeout ?? ""}
            disabled={locked("timeout")}
            onChange={(event) => update("timeout", event.target.value || null)}
            helperText={
              errors.timeout ??
              "Use 30s, 15m, or 2h. Blank keeps existing limits."
            }
          />
        </Box>
        <Box data-tour="autoRetry">
          {inherit("auto_retry")}
          <HelpControl topic="autoRetry">
            <FormControlLabel
              control={
                <Switch
                  checked={defaults.auto_retry}
                  disabled={locked("auto_retry")}
                  onChange={(_event, checked) => update("auto_retry", checked)}
                />
              }
              label="Allow automatic retries for jobs"
            />
          </HelpControl>
          <Typography variant="body2" color="text.secondary">
            Requires an enabled recovery policy. Each job can opt out.
          </Typography>
        </Box>
        <Box>
          {inherit("recovery")}
          <HelpControl topic="recovery" tour>
            <FormControlLabel
              control={
                <Switch
                  checked={defaults.recovery.enabled}
                  disabled={locked("recovery")}
                  onChange={(_event, checked) =>
                    update("recovery", {
                      ...defaults.recovery,
                      enabled: checked,
                    })
                  }
                />
              }
              label="Automatic recovery for new runs"
            />
          </HelpControl>
          <Box sx={{ height: 16 }} />
          <HelpTextField
            topic="retryLimit"
            tour
            label="Maximum automatic retries"
            error={Boolean(errors.retries)}
            fullWidth
            type="number"
            value={defaults.recovery.max_retries}
            disabled={locked("recovery")}
            onChange={(event) =>
              update("recovery", {
                ...defaults.recovery,
                max_retries: Number(event.target.value),
              })
            }
            slotProps={{ htmlInput: { min: 1, max: 2 } }}
            helperText={
              errors.retries ??
              "One or two additional attempts per eligible agent job."
            }
          />
        </Box>
        <Box>
          {inherit("cleanup_policy")}
          <HelpSelectField
            topic="cleanup"
            tour
            label="After a successful run"
            fullWidth
            value={settings.cleanup_policy}
            disabled={locked("cleanup_policy")}
            onChange={(event) =>
              ownerUpdate(
                "cleanup_policy",
                event.target.value === "merge_on_success"
                  ? "merge_on_success"
                  : event.target.value === "retain"
                    ? "retain"
                    : "clean_on_success",
              )
            }
            helperText={
              <>
                {" "}
                {settings.cleanup_policy === "merge_on_success"
                  ? "Fast-forwards the branch selected at launch. The checkout must be completely clean at launch and completion. Dirty, switched, or diverged branches fail and keep the run working copy."
                  : "Reports, commits, and history remain available. Run workflow can override this choice."}{" "}
              </>
            }
          >
            <MenuItem value="clean_on_success">
              Delete the working copy
            </MenuItem>
            <MenuItem value="retain">Keep the working copy</MenuItem>
            <MenuItem value="merge_on_success">
              Merge into the active branch, then delete working copies
            </MenuItem>
          </HelpSelectField>
        </Box>
      </Stack>
    </Box>
  );
}
