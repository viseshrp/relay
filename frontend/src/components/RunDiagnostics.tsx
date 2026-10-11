import {
  Accordion,
  AccordionDetails,
  AccordionSummary,
  Box,
  Button,
  Paper,
  Stack,
  Typography,
} from "@mui/material";

import { VirtualEvents } from "./RunWorkspaceShared";
import type { RunWorkspaceState } from "./useRunWorkspace";
export function RunDiagnostics({ state }: { state: RunWorkspaceState }) {
  const {
    panels,
    setPanel,
    detail,
    streamState,
    eventCursor,
    loadEvents,
    events,
  } = state;
  if (!detail) return null;
  return (
    <Accordion
      expanded={panels.advanced ?? false}
      onChange={(_, expanded) => setPanel("advanced", expanded)}
    >
      <AccordionSummary>Advanced diagnostics and saved files</AccordionSummary>
      <AccordionDetails>
        <Stack spacing={2}>
          <Box component="details" aria-label="Raw event details">
            <Box component="summary">Details</Box>
            <Paper variant="outlined" className="section-card">
              <Typography variant="body2" className="mono-wrap">
                Run {detail.id} · {detail.run_branch} · {detail.status} · SSE{" "}
                {streamState}
              </Typography>
              <Stack direction="row" sx={{ alignItems: "center", mb: 1 }}>
                <Typography variant="h6" sx={{ flex: 1 }}>
                  Event history
                </Typography>
                {eventCursor !== null && (
                  <Button onClick={() => void loadEvents(eventCursor)}>
                    Load next page
                  </Button>
                )}
              </Stack>
              <VirtualEvents
                key={`history-${detail.id}`}
                events={events}
                mode="history"
              />
            </Paper>
          </Box>
        </Stack>
      </AccordionDetails>
    </Accordion>
  );
}
