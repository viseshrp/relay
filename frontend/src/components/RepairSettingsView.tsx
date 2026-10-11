import { RepairRoleEditor } from "./RepairRoleEditor";
import { HelpControl, HelpTextField, HelpSelectField } from "./HelpTip";
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  MenuItem,
  Stack,
  Switch,
  Typography,
} from "@mui/material";

import { stageLabel } from "../navigation";

import { RepairReportSelector } from "./RepairReportSelector";

import type { RepairSettingsState } from "./useRepairSettings";
export function RepairSettingsView({ state }: { state: RepairSettingsState }) {
  const {
    close,
    stage,
    rule,
    disabled,
    promptDirty,
    onChange,
    defaults,
    settingsDisabled,
    sourceOutputs,
    onSourceOutput,
    resultType,
    role,
    setRole,
    onApply,
  } = state;
  return (
    <Dialog
      open
      maxWidth="md"
      fullWidth
      onClose={close}
      aria-labelledby="repair-settings-title"
    >
      <DialogTitle id="repair-settings-title">
        Repairs for {stageLabel(stage)}
      </DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Typography>
            Relay runs the fixer and verifier when this stage rejects its
            result. Later stages wait for a passing verification. Repair
            attempts stay in their own panel.
          </Typography>
          <HelpControl topic="repairs">
            <FormControlLabel
              label="Enable automatic repairs"
              control={
                <Switch
                  checked={rule.enabled !== false}
                  disabled={disabled || promptDirty}
                  onChange={(event) =>
                    onChange({ ...rule, enabled: event.target.checked })
                  }
                />
              }
            />
          </HelpControl>
          <HelpTextField
            topic="repairRounds"
            label="Maximum repair rounds"
            type="number"
            value={rule.max_rounds ?? defaults.max_rounds}
            disabled={settingsDisabled}
            slotProps={{
              htmlInput: { min: 1, max: defaults.max_allowed_rounds },
            }}
            onChange={(event) =>
              onChange({ ...rule, max_rounds: Number(event.target.value) })
            }
            helperText="Relay stops if no round passes. Restarting the service does not create more rounds."
          />
          <HelpTextField
            topic="resultOutput"
            label="Result output"
            value={rule.accepted_output}
            disabled={settingsDisabled}
            onChange={(event) =>
              onChange({ ...rule, accepted_output: event.target.value })
            }
            helperText="The stage and verifier must both declare this output."
          />
          <RepairReportSelector
            title="Review report"
            defaultArtifact="REVIEW.md"
            value={sourceOutputs[rule.accepted_output]}
            disabled={settingsDisabled}
            onChange={(selector) =>
              onSourceOutput(rule.accepted_output, selector)
            }
          />
          <HelpSelectField
            topic="resultOutput"
            label="Result type"
            size="small"
            disabled={settingsDisabled}
            value={resultType}
            onChange={(event) =>
              onChange({
                ...rule,
                accepted_value:
                  event.target.value === "null"
                    ? null
                    : event.target.value === "boolean"
                      ? true
                      : event.target.value === "number"
                        ? 1
                        : "Yes",
              })
            }
          >
            <MenuItem value="string">Text</MenuItem>
            <MenuItem value="boolean">True or false</MenuItem>
            <MenuItem value="number">Number</MenuItem>
            <MenuItem value="null">Null</MenuItem>
          </HelpSelectField>
          {typeof rule.accepted_value === "boolean" ? (
            <HelpSelectField
              topic="resultOutput"
              label="Passing result"
              size="small"
              value={String(rule.accepted_value)}
              disabled={settingsDisabled}
              onChange={(event) =>
                onChange({
                  ...rule,
                  accepted_value: event.target.value === "true",
                })
              }
            >
              <MenuItem value="true">True</MenuItem>
              <MenuItem value="false">False</MenuItem>
            </HelpSelectField>
          ) : rule.accepted_value === null ? (
            <Typography>Passing result: null</Typography>
          ) : (
            <HelpTextField
              topic="resultOutput"
              label="Passing result"
              value={rule.accepted_value ?? "Yes"}
              type={typeof rule.accepted_value === "number" ? "number" : "text"}
              disabled={settingsDisabled}
              onChange={(event) =>
                onChange({
                  ...rule,
                  accepted_value:
                    typeof rule.accepted_value === "number"
                      ? Number(event.target.value)
                      : event.target.value,
                })
              }
            />
          )}
          <Stack direction="row" spacing={1}>
            {(["fix", "verify"] as const).map((value) => (
              <Button
                key={value}
                variant={role === value ? "contained" : "outlined"}
                disabled={promptDirty}
                onClick={() => setRole(value)}
              >
                {value === "fix" ? "Fixer settings" : "Verifier settings"}
              </Button>
            ))}
          </Stack>
          <RepairRoleEditor state={state} />
          {promptDirty && (
            <Alert severity="warning">
              Save the instructions before changing repair settings or closing
              this panel.
            </Alert>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button disabled={promptDirty} onClick={close}>
          Cancel
        </Button>
        <Button disabled={disabled || promptDirty} onClick={onApply}>
          Done
        </Button>
      </DialogActions>
    </Dialog>
  );
}
