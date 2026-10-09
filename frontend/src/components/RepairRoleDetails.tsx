import { Box, Typography } from "@mui/material";
import { stageLabel } from "../navigation";
import type { RetryConfiguration, RunNode } from "../types";

type RepairRole = NonNullable<RunNode["repair_settings"]>["roles"][string];

export function RepairRoleDetails({
  role,
  saved,
  current,
}: {
  role: string;
  saved: RepairRole;
  current: RetryConfiguration | null | undefined;
}) {
  const tools = saved.agents?.length
    ? saved.agents
    : Object.keys(saved.agent_options ?? {});
  const choices = current
    ? [
        {
          agent: current.agent_id,
          effort: current.effort,
          permission: current.permission_mode,
        },
      ]
    : tools.map((agent) => ({
        agent,
        effort: saved.agent_options?.[agent]?.effort,
        permission: saved.agent_options?.[agent]?.permission_mode,
      }));
  return (
    <Box
      component="section"
      aria-label={`Repair settings for ${stageLabel(role)}`}
    >
      <Typography variant="subtitle2">{stageLabel(role)}</Typography>
      <Box component="dl" className="data-rows">
        <Box className="data-row">
          <Typography component="dt">Model</Typography>
          <Typography component="dd">
            {current?.model_value ??
              saved.model ??
              (saved.type === "agent" ? "Captured workflow model" : "Command")}
          </Typography>
        </Box>
        {saved.type === "agent" &&
          choices.map((choice) => (
            <Box key={choice.agent}>
              <Box className="data-row">
                <Typography component="dt">Agent</Typography>
                <Typography component="dd">
                  {stageLabel(choice.agent)}
                </Typography>
              </Box>
              <Box className="data-row">
                <Typography component="dt">Thinking effort</Typography>
                <Typography component="dd">
                  {choice.effort ?? "Agent’s default"}
                </Typography>
              </Box>
              <Box className="data-row">
                <Typography component="dt">Permissions</Typography>
                <Typography component="dd">
                  {choice.permission ?? "Agent’s default"}
                </Typography>
              </Box>
            </Box>
          ))}
      </Box>
      {saved.type === "agent" && (
        <Typography variant="body2" color="text.secondary" sx={{ mt: 1 }}>
          {current
            ? "Saved override for this attempt."
            : choices.length
              ? "Captured workflow defaults."
              : "Tool and settings follow the captured workflow."}
        </Typography>
      )}
    </Box>
  );
}
