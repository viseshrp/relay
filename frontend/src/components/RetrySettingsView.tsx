import { HelpSelectField, HelpTextField } from "./HelpTip";
import {
  Alert,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  LinearProgress,
  MenuItem,
  Stack,
  Typography,
} from "@mui/material";

import { stageLabel } from "../navigation";

import type { RetrySettingsState } from "./useRetrySettings";
export function RetrySettingsView({ state }: { state: RetrySettingsState }) {
  const {
    onClose,
    submitting,
    purpose,
    problem,
    agents,
    agentId,
    changeAgent,
    models,
    model,
    changeModel,
    choices,
    configuration,
    error,
    editable,
    selection,
    setSelection,
    changed,
    currentEffort,
    selector,
    permissionSelection,
    setPermissionSelection,
    currentPermission,
    handoff,
    handoffTooLong,
    setHandoff,
    submit,
  } = state;
  return (
    <Dialog
      open
      onClose={submitting ? undefined : onClose}
      fullWidth
      maxWidth="sm"
    >
      <DialogTitle>
        {purpose === "pending" ? "Change" : "Retry"}{" "}
        {stageLabel(problem.scope_path)}{" "}
        {purpose === "pending" ? "settings" : "with settings"}
      </DialogTitle>
      <DialogContent>
        <Stack spacing={2} sx={{ pt: 1 }}>
          <Typography variant="body2">
            {purpose === "pending"
              ? "Choose settings for this upcoming job. Saving keeps the run paused. Completed work and captured instructions stay saved."
              : "Choose the tool and model for this step's new attempts. Completed steps, prompts, and earlier attempts stay saved. Automatic retries keep your choice."}
          </Typography>
          <HelpSelectField
            topic="retry"
            label="Tool"
            fullWidth
            disabled={!agents || submitting}
            value={agentId}
            onChange={(event) => changeAgent(event.target.value)}
          >
            {!agents && (
              <MenuItem value={problem.agent_id}>
                {stageLabel(problem.agent_id)}
              </MenuItem>
            )}
            {agents?.agents.map((agent) => (
              <MenuItem
                key={agent.id}
                value={agent.id}
                disabled={!agent.installed}
              >
                {agent.display_name}
                {agent.installed ? "" : " (not installed)"}
              </MenuItem>
            ))}
          </HelpSelectField>
          <HelpSelectField
            topic="model"
            label="Model"
            placeholder="Choose a model"
            fullWidth
            disabled={models?.agentId !== agentId || submitting}
            value={model}
            onChange={(event) => changeModel(event.target.value)}
          >
            {model && !choices.some((choice) => choice.value === model) && (
              <MenuItem value={model}>{model}</MenuItem>
            )}
            {choices.map((choice) => (
              <MenuItem key={choice.value} value={choice.value}>
                {choice.name}
              </MenuItem>
            ))}
          </HelpSelectField>
          {!configuration && !error && (
            <LinearProgress aria-label="Loading effort choices" />
          )}
          {error && <Alert severity="error">{error}</Alert>}
          {configuration && (
            <HelpSelectField<number>
              topic="effort"
              label="Effort"
              fullWidth
              disabled={!editable || submitting}
              value={selection}
              onChange={(event) => setSelection(Number(event.target.value))}
            >
              {!changed && (
                <MenuItem value={0}>
                  Keep current effort ({currentEffort})
                </MenuItem>
              )}
              <MenuItem value={1}>Agent’s default</MenuItem>
              {editable &&
                selector?.choices.map((choice, index) => (
                  <MenuItem key={choice.value} value={index + 2}>
                    {choice.name}
                  </MenuItem>
                ))}
            </HelpSelectField>
          )}
          {configuration && !editable && (
            <Typography variant="body2" color="text.secondary">
              {selector?.transport === "native"
                ? `Effort is ${selector.current_value}, included in this model.`
                : "This model does not offer a separate effort setting."}
            </Typography>
          )}
          {configuration && (
            <HelpSelectField<number>
              topic="permissions"
              label="Permission mode"
              fullWidth
              disabled={!configuration.permission_mode || submitting}
              value={permissionSelection}
              onChange={(event) =>
                setPermissionSelection(Number(event.target.value))
              }
            >
              {!changed && (
                <MenuItem value={0}>
                  Keep current permission mode ({currentPermission})
                </MenuItem>
              )}
              <MenuItem value={1}>Agent’s default</MenuItem>
              {configuration.permission_mode?.choices.map((choice, index) => (
                <MenuItem key={choice.value} value={index + 2}>
                  {choice.name}
                </MenuItem>
              ))}
            </HelpSelectField>
          )}
          {changed && (
            <>
              <HelpTextField
                topic="instructions"
                label="Handoff instructions"
                multiline
                minRows={4}
                maxRows={8}
                value={handoff}
                disabled={submitting}
                error={handoffTooLong}
                helperText={
                  handoffTooLong
                    ? `Use at most ${problem.handoff_prompt_max_bytes} UTF-8 bytes.`
                    : "These instructions follow this step's original prompts. Edit them to tell the new model how to continue."
                }
                onChange={(event) => setHandoff(event.target.value)}
              />
              <Button
                disabled={submitting}
                onClick={() => setHandoff(problem.default_handoff_prompt ?? "")}
              >
                Use default handoff
              </Button>
            </>
          )}
        </Stack>
      </DialogContent>
      <DialogActions>
        <Button disabled={submitting} onClick={onClose}>
          Cancel
        </Button>
        <Button
          variant="contained"
          disabled={
            !configuration ||
            submitting ||
            (changed && (!handoff.trim() || handoffTooLong)) ||
            (purpose === "pending" &&
              !changed &&
              selection === 0 &&
              permissionSelection === 0)
          }
          onClick={() => void submit()}
        >
          {purpose === "pending"
            ? submitting
              ? "Saving…"
              : "Save settings"
            : submitting
              ? "Starting retry…"
              : "Retry with settings"}
        </Button>
      </DialogActions>
    </Dialog>
  );
}
