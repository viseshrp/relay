import { useQuery } from "@tanstack/react-query";

import { getLogs } from "@/api/phases";
import { LogViewer } from "@/components/shared/LogViewer";
import { useLogStream } from "@/hooks/useLogStream";

export function PhaseLogsTab({
  runId,
  phaseId,
  attemptNumber,
}: {
  runId: string;
  phaseId: string;
  attemptNumber: number;
}) {
  const { data } = useQuery({
    queryKey: ["logs", runId, phaseId, attemptNumber],
    queryFn: () => getLogs(runId, phaseId, attemptNumber),
  });
  const { lines: streamedLines } = useLogStream(runId, phaseId, attemptNumber);
  return <LogViewer lines={[...(data?.lines ?? []), ...streamedLines]} />;
}
