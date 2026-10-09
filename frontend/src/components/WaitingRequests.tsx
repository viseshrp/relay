import { Alert, Box, Button, Stack, Typography } from "@mui/material";
import { useEffect, useRef, useState } from "react";
import { stageLabel } from "../navigation";
import type { ArtifactRecord, RunInteraction } from "../types";
import { ReviewRequest } from "./RunReview";

export function WaitingRequests({
  requests,
  runId,
  artifacts,
  selected,
  hasMore,
  onMore,
  onAnswered,
}: {
  requests: RunInteraction[];
  runId: string;
  artifacts: ArtifactRecord[];
  selected: string | null;
  hasMore: boolean;
  onMore: () => void;
  onAnswered: () => Promise<void>;
}) {
  const [opened, setOpened] = useState<string | null>(selected);
  const [focusRequest, setFocusRequest] = useState(0);
  const first = requests[0]?.id;
  const form = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (selected) setOpened(selected);
  }, [selected]);
  const shown = requests.find((request) => request.id === opened);
  useEffect(() => {
    if (!focusRequest || !shown) return;
    form.current?.scrollIntoView({ block: "start" });
    form.current
      ?.querySelector<HTMLElement>(
        "[data-owner-response] button, [data-owner-response] input:not([aria-hidden=true]), [data-owner-response] textarea, [data-owner-response] [role=combobox]",
      )
      ?.focus({ preventScroll: true });
  }, [focusRequest, shown?.id]);
  function respond(id: string) {
    setOpened(id);
    setFocusRequest((current) => current + 1);
  }
  if (!first && !hasMore) return null;
  return (
    <Stack spacing={1} component="section" aria-label="Waiting for you">
      {requests.map((request) => (
        <Alert
          key={request.id}
          severity="warning"
          action={
            <Button color="inherit" onClick={() => respond(request.id)}>
              Respond
            </Button>
          }
        >
          <Typography variant="subtitle1">
            Waiting for you · {stageLabel(request.scope_path)}
          </Typography>
          <Typography sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
            {String(
              request.request.prompt ??
                "Choose a response to continue this job.",
            )}
          </Typography>
        </Alert>
      ))}
      {shown && (
        <Box ref={form} sx={{ scrollMarginTop: 90 }}>
          <ReviewRequest
            key={shown.id}
            interaction={shown}
            runId={runId}
            artifacts={artifacts}
            selected={shown.id === selected}
            onAnswered={onAnswered}
          />
        </Box>
      )}
      {hasMore && <Button onClick={onMore}>Load more requests</Button>}
    </Stack>
  );
}
