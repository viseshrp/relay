import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Button,
  Paper,
  Stack,
  Typography,
} from "@mui/material";

import type { RunNode } from "../types";
import { countLabel } from "../count";

import { stageLabel, statusLabel } from "../navigation";

import { RepairRoleDetails } from "./RepairRoleDetails";

import type { RunWorkspaceState } from "./useRunWorkspace";
export function RunRepairDetails({ state }: { state: RunWorkspaceState }) {
  const {
    panels,
    setPanel,
    repairGroups,
    repairChildren,
    dispatchPaused,
    showStep,
    detail,
  } = state;
  if (!detail) return null;
  return (
    <Accordion
      expanded={panels.repairs ?? false}
      onChange={(_, expanded) => setPanel("repairs", expanded)}
    >
      <AccordionSummary>
        <Typography>Repairs · {repairGroups.length} configured</Typography>
      </AccordionSummary>
      <AccordionDetails>
        <Stack spacing={2}>
          <Typography variant="body2">
            Relay handles these repairs behind each stage. Reports, attempts,
            and tool messages remain saved. Settings for this run are captured;
            edit the workflow to change future runs.
          </Typography>
          {repairGroups.map((group) => {
            const settings = group.repair_settings!;
            const children = repairChildren.get(group.repair_for!) ?? [];
            const round = Math.max(
              0,
              ...children.map((node) => node.loop_index ?? 0),
            );
            const roleNodes = new Map<string, RunNode>();
            for (const child of children) {
              // root.hidden#2.verify is the direct verifier for round 2;
              // a nested child must not replace its parent's role settings.
              if (
                child.parent_scope !== `${group.scope_path}#${child.loop_index}`
              )
                continue;
              const previous = roleNodes.get(child.node_id);
              if (
                !previous ||
                (child.loop_index ?? 0) >= (previous.loop_index ?? 0)
              )
                roleNodes.set(child.node_id, child);
            }
            const held =
              dispatchPaused &&
              !["succeeded", "skipped", "failed", "canceled"].includes(
                group.status,
              );
            return (
              <Paper
                key={group.id}
                variant="outlined"
                className="section-card"
                role="region"
                aria-label={`Repairs for ${stageLabel(group.repair_for!)}`}
              >
                <Typography variant="h6">
                  {stageLabel(group.repair_for!)} ·{" "}
                  {held ? "Repairs paused" : statusLabel(group.status)}
                </Typography>
                <Typography variant="body2">
                  {round
                    ? `Round ${round} of ${settings.max_rounds}`
                    : `Up to ${countLabel(settings.max_rounds, "round")}`}
                  {settings.legacy
                    ? " · Existing workflow loop"
                    : ` · ${settings.accepted_output} must equal ${JSON.stringify(settings.accepted_value)}`}
                </Typography>
                {Object.entries(settings.roles).map(([role, value]) => {
                  const child = roleNodes.get(role);
                  const current =
                    child?.pending_settings ?? child?.retry_settings;
                  return (
                    <RepairRoleDetails
                      key={role}
                      role={role}
                      saved={value}
                      current={current}
                    />
                  );
                })}
                {settings.fix_instruction && (
                  <Typography variant="body2" sx={{ mt: 1 }}>
                    Fixer instructions: {settings.fix_instruction}
                  </Typography>
                )}
                {settings.verify_instruction && (
                  <Typography variant="body2" sx={{ mt: 1 }}>
                    Verifier instructions: {settings.verify_instruction}
                  </Typography>
                )}
                <Stack spacing={1} sx={{ mt: 1, alignItems: "flex-start" }}>
                  {children.map((node) => (
                    <Button
                      key={node.id}
                      onClick={() => showStep(node.scope_path)}
                    >
                      {stageLabel(node.scope_path)} · {statusLabel(node.status)}
                    </Button>
                  ))}
                </Stack>
              </Paper>
            );
          })}
          <Button
            sx={{ alignSelf: "flex-start" }}
            href={`/?view=workflows&project=${encodeURIComponent(detail.project_id)}&workflow=${encodeURIComponent(detail.workflow_key)}`}
          >
            Edit repairs for future runs
          </Button>
        </Stack>
      </AccordionDetails>
    </Accordion>
  );
}
