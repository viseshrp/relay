import { ActionIcon } from "./ActionIcon";
import { HelpLabel, HelpTextField } from "./HelpTip";
import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Alert,
  Box,
  Stack,
  Typography,
} from "@mui/material";

import type { AgentOptions } from "../types";
import { AgentConfiguration } from "./AgentConfiguration";
import { ModelPicker } from "./ModelPicker";

import type { DefaultSettingsFormState } from "./useDefaultSettingsForm";
export function DefaultModelSettings({
  state,
}: {
  state: DefaultSettingsFormState;
}) {
  const { inherit, agents, defaults, project, locked, providerChange } = state;
  return (
    <Box data-tour="providers" className="settings-group">
      <Typography variant="h6">
        <HelpLabel topic="providers">Agent models and thinking</HelpLabel>
      </Typography>
      <Typography color="text.secondary" variant="body2" sx={{ mb: 1 }}>
        Defaults apply to the same exact model. Saved workflow choices take
        precedence.
      </Typography>
      {inherit("providers")}
      {agents.map((agent) => {
        const value = defaults.providers[agent.id] ?? { model: null };
        const options: AgentOptions = {
          effort: value.effort ?? undefined,
          permission_mode: value.permission_mode ?? undefined,
        };
        return (
          <Accordion
            key={agent.id}
            disableGutters
            slotProps={{ transition: { unmountOnExit: true } }}
          >
            <AccordionSummary expandIcon={<ActionIcon name="down" />}>
              <Stack
                direction={{ xs: "column", sm: "row" }}
                spacing={1}
                sx={{
                  width: "100%",
                  minWidth: 0,
                  justifyContent: "space-between",
                }}
              >
                <Typography>{agent.display_name}</Typography>
                <Typography
                  color="text.secondary"
                  variant="body2"
                  sx={{ overflowWrap: "anywhere", minWidth: 0 }}
                >
                  {value.model ?? "No saved model"}
                </Typography>
              </Stack>
            </AccordionSummary>
            <AccordionDetails>
              <Stack spacing={2}>
                <ModelPicker
                  defaultLabel="No saved model"
                  agents={[agent]}
                  value={value.model ?? ""}
                  project={project}
                  disabled={locked("providers")}
                  onChange={(model) =>
                    providerChange(agent.id, {
                      model: model || null,
                      effort: null,
                      permission_mode: null,
                    })
                  }
                />
                <HelpTextField
                  topic="model"
                  label={`${agent.display_name} exact model`}
                  value={value.model ?? ""}
                  disabled={locked("providers")}
                  onChange={(event) =>
                    providerChange(agent.id, {
                      model: event.target.value || null,
                      effort: null,
                      permission_mode: null,
                    })
                  }
                  helperText="Model values preserve case. Changing the model clears its saved effort and permissions."
                />
                <AgentConfiguration
                  agent={agent}
                  model={value.model ?? ""}
                  options={options}
                  project={project}
                  disabled={locked("providers")}
                  labels={{
                    effort: "Thinking effort",
                    permission_mode: "What the agent may do",
                  }}
                  defaultLabel="Agent’s default"
                  onChange={(field, selected) =>
                    providerChange(agent.id, {
                      ...value,
                      [field]: selected || null,
                    })
                  }
                />
                {value.permission_mode && (
                  <Alert severity="info">
                    New jobs using this exact model inherit this permission
                    choice unless the workflow sets its own. Review the agent's
                    description before saving.
                  </Alert>
                )}
              </Stack>
            </AccordionDetails>
          </Accordion>
        );
      })}
    </Box>
  );
}
