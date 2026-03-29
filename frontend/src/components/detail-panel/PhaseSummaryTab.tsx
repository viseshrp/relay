import type { PhaseDetail } from "@/types/api";

import { MarkdownRenderer } from "@/components/shared/MarkdownRenderer";
import { Card } from "@/components/ui/card";

export function PhaseSummaryTab({ phase }: { phase: PhaseDetail }) {
  const latestAttempt = phase.attempts[phase.attempts.length - 1];
  return (
    <Card className="space-y-4">
      <div>
        <h3 className="text-lg font-semibold capitalize">{phase.phase_type.replaceAll("_", " ")}</h3>
        <p className="text-sm text-muted-foreground">Latest status: {phase.status}</p>
      </div>
      {latestAttempt?.error_message ? (
        <div className="rounded-[1.5rem] bg-destructive/10 p-4 text-sm text-foreground">{latestAttempt.error_message}</div>
      ) : (
        <MarkdownRenderer content={`No structured summary is available for this phase yet.\n\nCurrent attempt: ${phase.current_attempt}.`} />
      )}
    </Card>
  );
}
