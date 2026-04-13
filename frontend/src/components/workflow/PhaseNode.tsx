import type { PhaseSummary } from "@/types/api";

import { StatusBadge } from "@/components/shared/StatusBadge";
import { Badge } from "@/components/ui/badge";
import { formatDuration } from "@/lib/utils";
import { cn } from "@/lib/utils";

export function PhaseNode({
  phase,
  selected,
  onSelect,
}: {
  phase: PhaseSummary;
  selected: boolean;
  onSelect: () => void;
}) {
  const latestAttempt = phase.latest_attempt;
  let durationLabel: string | null = null;
  if (latestAttempt?.started_at && latestAttempt.ended_at && ["succeeded", "failed", "cancelled"].includes(phase.status)) {
    durationLabel = formatDuration(latestAttempt.started_at, latestAttempt.ended_at);
  }

  return (
    <button
      type="button"
      onClick={onSelect}
      className={cn(
        "w-full rounded-[1.75rem] border border-border bg-card p-4 text-left transition hover:-translate-y-0.5",
        selected && "border-primary ring-2 ring-ring/30",
      )}
    >
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="font-semibold capitalize">{phase.phase_type.replaceAll("_", " ")}</div>
          <div className="mt-1 text-xs text-muted-foreground">Step {phase.sequence_number + 1}</div>
        </div>
        <StatusBadge status={phase.status} />
      </div>
      {phase.current_attempt > 1 ? <Badge className="mt-3 w-fit bg-accent text-accent-foreground">Attempt {phase.current_attempt}</Badge> : null}
      {durationLabel ? <div className="mt-3 text-xs text-muted-foreground">{durationLabel}</div> : null}
    </button>
  );
}
