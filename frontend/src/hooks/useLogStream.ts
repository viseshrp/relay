import { useEffect, useState } from "react";

import { wsClient } from "@/api/ws";
import type { LogEvent } from "@/types/ws";

export function useLogStream(runId: string | undefined, phaseId: string | undefined, attemptNumber: number | undefined) {
  const [lines, setLines] = useState<string[]>([]);

  useEffect(() => {
    if (!runId || !phaseId || attemptNumber === undefined) {
      return;
    }
    setLines([]);
    return wsClient.subscribe((event) => {
      const logEvent = event as LogEvent;
      if (logEvent.type !== "log") {
        return;
      }
      if (logEvent.run_id === runId && logEvent.phase_id === phaseId && logEvent.attempt_number === attemptNumber) {
        setLines((current) => [...current, logEvent.line]);
      }
    });
  }, [attemptNumber, phaseId, runId]);

  return { lines };
}
