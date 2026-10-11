import {
  Alert,
  Accordion,
  AccordionDetails,
  AccordionSummary,
  FormControlLabel,
  Switch,
  Typography,
} from "@mui/material";

import { stageLabel } from "../navigation";

import type { RunWorkspaceState } from "./useRunWorkspace";
export function RunSettingsDetails({ state }: { state: RunWorkspaceState }) {
  const {
    panels,
    setPanel,
    detail,
    recoveryBusy,
    configureRecovery,
    recovery,
  } = state;
  if (!detail) return null;
  return (
    <Accordion
      expanded={panels.settings ?? false}
      onChange={(_, expanded) => setPanel("settings", expanded)}
    >
      <AccordionSummary>Run settings</AccordionSummary>
      <AccordionDetails>
        {" "}
        <FormControlLabel
          sx={{ mt: 2 }}
          control={
            <Switch
              checked={detail.recovery?.enabled === true}
              disabled={
                recoveryBusy ||
                ["succeeded", "canceled"].includes(detail.status)
              }
              onChange={(event) => void configureRecovery(event.target.checked)}
            />
          }
          label="Automatic recovery"
        />
        <Typography variant="body2" color="text.secondary">
          Eligible agent steps can retry up to{" "}
          {detail.recovery?.max_retries ?? 2} times. Retries keep their model,
          settings, and original instructions. Turning this off cancels queued
          recovery and keeps the remaining budget unchanged.
        </Typography>
        {recovery && ["blocked", "exhausted"].includes(recovery.state) && (
          <Alert severity="warning" sx={{ mt: 2 }}>
            {recovery.message}
          </Alert>
        )}
        {recovery?.instruction && (
          <Accordion sx={{ mt: 2 }}>
            <AccordionSummary>Automatic retry instruction</AccordionSummary>
            <AccordionDetails>
              <Typography variant="body2">
                {stageLabel(recovery.scope_path)} · Retry{" "}
                {recovery.retry_number} of {detail.recovery.max_retries} ·{" "}
                {recovery.state}
              </Typography>
              <Typography component="pre" className="activity-text">
                {recovery.instruction}
              </Typography>
            </AccordionDetails>
          </Accordion>
        )}
      </AccordionDetails>
    </Accordion>
  );
}
