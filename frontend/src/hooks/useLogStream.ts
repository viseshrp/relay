import { useEffect, useState } from "react";

import { wsClient } from "@/api/ws";

export function useLogStream(runId: string | undefined, phaseId: string | undefined, attemptNumber: number | undefined) {
  const [lines, setLines] = useState<string[]>([]);

  useEffect(() => {
    if (!runId || !phaseId || attemptNumber === undefined) {
      return;
    }
    setLines([]);
    return wsClient.subscribe((event) => {
      if (event.type !== "log") {
        return;
      }
      if (event.run_id === runId && event.phase_id === phaseId && event.attempt_number === attemptNumber) {
        setLines((current) => [...current, event.line]);
      }
    });
  }, [attemptNumber, phaseId, runId]);

  return { lines };
}
