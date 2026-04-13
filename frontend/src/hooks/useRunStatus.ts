import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";

import { wsClient } from "@/api/ws";
import type { RunDetail } from "@/types/api";
import type { ErrorEvent, RelayWsEvent } from "@/types/ws";

export function useRunStatus(runId: string | undefined) {
  const queryClient = useQueryClient();
  const [errors, setErrors] = useState<ErrorEvent[]>([]);

  useEffect(() => {
    if (!runId) {
      return;
    }
    setErrors([]);
    wsClient.subscribeRun(runId);
    const unsubscribe = wsClient.subscribe((event: RelayWsEvent) => {
      if (event.run_id !== runId) {
        return;
      }
      if (event.type === "exploration_finalized" || event.type === "review_results") {
        void queryClient.invalidateQueries({ queryKey: ["run", runId] });
        return;
      }
      if (event.type === "error") {
        setErrors((current) => [event, ...current].slice(0, 5));
        void queryClient.invalidateQueries({ queryKey: ["run", runId] });
        return;
      }
      queryClient.setQueryData<RunDetail>(["run", runId], (current) => {
        if (!current) {
          return current;
        }
        if (event.type === "workflow_status") {
          return { ...current, status: event.status, updated_at: event.timestamp };
        }
        if (event.type === "phase_status") {
          return {
            ...current,
            phases: current.phases.map((phase) =>
              phase.id === event.phase_id
                ? { ...phase, status: event.status as RunDetail["phases"][number]["status"], current_attempt: event.attempt_number }
                : phase,
            ),
          };
        }
        return current;
      });
    });
    return () => {
      unsubscribe();
      wsClient.unsubscribeRun(runId);
    };
  }, [queryClient, runId]);

  return { errors };
}
