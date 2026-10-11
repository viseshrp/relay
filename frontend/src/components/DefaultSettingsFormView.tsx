import { DefaultModelSettings } from "./DefaultModelSettings";
import { DefaultRecoverySettings } from "./DefaultRecoverySettings";

import { ActionIcon } from "./ActionIcon";
import { HelpLabel, HelpTextField } from "./HelpTip";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
  Typography,
} from "@mui/material";

import { EnvironmentEditor } from "./EnvironmentEditor";
import { SharedCommandsEditor } from "./SharedCommandsEditor";

import type { DefaultSettingsFormState } from "./useDefaultSettingsForm";
export function DefaultSettingsFormView({
  state,
}: {
  state: DefaultSettingsFormState;
}) {
  const {
    inherit,
    settings,
    agents,
    locked,
    ownerUpdate,
    prefix,
    defaults,
    update,
    errors,
    tourActive,
    repairOpen,
    setRepairOpen,
  } = state;
  return (
    <Stack spacing={3}>
      <Box data-tour="agentOrder" className="settings-group">
        <Typography variant="h6">
          <HelpLabel topic="agentOrder">Default agent order</HelpLabel>
        </Typography>
        <Typography color="text.secondary" variant="body2">
          Job and workflow tools come first. Relay checks the same exact model
          in this order.
        </Typography>
        {inherit("agent_preferences")}
        <Stack spacing={1} sx={{ mt: 1 }}>
          {settings.agent_preferences.map((id, index) => (
            <Stack
              key={id}
              direction="row"
              spacing={1}
              useFlexGap
              sx={{ alignItems: "center", flexWrap: "wrap" }}
            >
              <Typography sx={{ flex: 1 }}>
                {index + 1}.{" "}
                {agents.find((agent) => agent.id === id)?.display_name ?? id}
              </Typography>
              <Button
                size="small"
                disabled={locked("agent_preferences") || index === 0}
                aria-label={`Move ${id} up`}
                onClick={() => {
                  const order = [...settings.agent_preferences];
                  [order[index - 1], order[index]] = [
                    order[index],
                    order[index - 1],
                  ];
                  ownerUpdate("agent_preferences", order);
                }}
              >
                Move up
              </Button>
              <Button
                size="small"
                disabled={locked("agent_preferences")}
                aria-label={`Remove ${id} from default order`}
                onClick={() =>
                  ownerUpdate(
                    "agent_preferences",
                    settings.agent_preferences.filter((value) => value !== id),
                  )
                }
              >
                Remove
              </Button>
            </Stack>
          ))}
          {settings.agent_preferences.length === 0 && (
            <Typography variant="body2">
              No global agent order. Workflows must choose their tools.
            </Typography>
          )}
          <FormControl size="small" sx={{ width: "100%", maxWidth: 320 }}>
            <InputLabel id={`${prefix}-agent`} shrink>
              Add an agent
            </InputLabel>
            <Select
              displayEmpty
              renderValue={() => "Choose an agent"}
              labelId={`${prefix}-agent`}
              label="Add an agent"
              value=""
              disabled={locked("agent_preferences")}
              onChange={(event) =>
                ownerUpdate("agent_preferences", [
                  ...settings.agent_preferences,
                  event.target.value,
                ])
              }
            >
              {agents
                .filter(
                  (agent) => !settings.agent_preferences.includes(agent.id),
                )
                .map((agent) => (
                  <MenuItem key={agent.id} value={agent.id}>
                    {agent.display_name}
                    {agent.installed ? "" : " (not installed)"}
                  </MenuItem>
                ))}
            </Select>
          </FormControl>
        </Stack>
      </Box>
      <Box>
        {inherit("model")}
        <HelpTextField
          topic="sharedModel"
          tour
          label="Shared default model"
          fullWidth
          value={defaults.model ?? ""}
          disabled={locked("model")}
          onChange={(event) => update("model", event.target.value || null)}
          helperText="Optional. Leave blank to use the preferred agent’s model."
        />
      </Box>
      <DefaultModelSettings state={state} />
      <Box data-tour="commands" className="settings-group">
        <Typography variant="h6">
          <HelpLabel topic="commands">Shared commands</HelpLabel>
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Named programs and arguments for command jobs.
        </Typography>
        {inherit("commands")}
        <SharedCommandsEditor
          value={defaults.commands}
          disabled={locked("commands")}
          onChange={(commands) => update("commands", commands)}
        />
      </Box>
      <Box data-tour="environment" className="settings-group">
        <Typography variant="h6">
          <HelpLabel topic="environment">Environment variables</HelpLabel>
        </Typography>
        <Typography variant="body2" color="text.secondary">
          Defaults for command jobs. Workflow and job variables take precedence.
          Values are stored locally and captured in runs; output is not masked.
        </Typography>
        {inherit("env")}
        <EnvironmentEditor
          value={defaults.env}
          disabled={locked("env")}
          onChange={(env) => update("env", env)}
        />
      </Box>
      <DefaultRecoverySettings state={state} />
      <Box data-tour="repairs">
        <Typography variant="h6" sx={{ mb: 1 }}>
          <HelpLabel topic="repairs">New repair rules</HelpLabel>
        </Typography>
        <Accordion
          expanded={tourActive || repairOpen}
          onChange={(_event, expanded) => setRepairOpen(expanded)}
        >
          <AccordionSummary expandIcon={<ActionIcon name="down" />}>
            Defaults for new repair rules
          </AccordionSummary>
          <AccordionDetails>
            <Stack spacing={2}>
              <Typography variant="body2">
                Used when adding a repair rule in the editor. Saved repair rules
                keep their rounds and instructions.
              </Typography>
              {inherit("repairs")}
              <HelpTextField
                topic="repairRounds"
                tour
                label="Maximum repair rounds"
                error={Boolean(errors.rounds)}
                helperText={errors.rounds}
                type="number"
                value={defaults.repairs.max_rounds}
                disabled={locked("repairs")}
                onChange={(event) =>
                  update("repairs", {
                    ...defaults.repairs,
                    max_rounds: Number(event.target.value),
                  })
                }
                slotProps={{ htmlInput: { min: 1, max: 100 } }}
              />
              <HelpTextField
                topic="fixer"
                tour
                label="Fixer instructions"
                multiline
                minRows={3}
                maxRows={8}
                value={defaults.repairs.fix_instruction}
                disabled={locked("repairs")}
                onChange={(event) =>
                  update("repairs", {
                    ...defaults.repairs,
                    fix_instruction: event.target.value,
                  })
                }
              />
              <HelpTextField
                topic="verifier"
                tour
                label="Verifier instructions"
                multiline
                minRows={3}
                maxRows={8}
                value={defaults.repairs.verify_instruction}
                disabled={locked("repairs")}
                onChange={(event) =>
                  update("repairs", {
                    ...defaults.repairs,
                    verify_instruction: event.target.value,
                  })
                }
              />
            </Stack>
          </AccordionDetails>
        </Accordion>
      </Box>
    </Stack>
  );
}
