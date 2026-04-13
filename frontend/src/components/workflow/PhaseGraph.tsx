import type { PhaseSummary } from "@/types/api";

import { PhaseNode } from "@/components/workflow/PhaseNode";
import { ReviewFixLoopIndicator } from "@/components/workflow/ReviewFixLoopIndicator";
import { cn } from "@/lib/utils";

export function PhaseGraph({
  phases,
  selectedPhaseId,
  onSelect,
  compact = false,
  loopCount = 0,
  loopLimit = 0,
}: {
  phases: PhaseSummary[];
  selectedPhaseId: string | null;
  onSelect: (phaseId: string) => void;
  compact?: boolean;
  loopCount?: number;
  loopLimit?: number;
}) {
  if (compact) {
    return (
      <div className="space-y-3">
        {phases.map((phase) => (
          <button
            key={phase.id}
            type="button"
            onClick={() => onSelect(phase.id)}
            className={cn(
              "flex w-full items-center gap-3 rounded-2xl px-3 py-2 text-left transition hover:bg-card/60",
              selectedPhaseId === phase.id && "bg-card shadow-sm",
            )}
          >
            <span
              className={cn(
                "h-3 w-3 rounded-full bg-muted",
                phase.status === "running" && "bg-sky-500",
                phase.status === "succeeded" && "bg-emerald-500",
                phase.status === "failed" && "bg-rose-500",
                phase.status === "waiting_for_user" && "bg-amber-500",
              )}
            />
            <span className="text-xs font-medium capitalize">{phase.phase_type.replaceAll("_", " ")}</span>
          </button>
        ))}
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {phases.map((phase, index) => (
        <div key={phase.id} className="space-y-4">
          <PhaseNode phase={phase} selected={selectedPhaseId === phase.id} onSelect={() => onSelect(phase.id)} />
          {phase.phase_type === "execution" ? <ReviewFixLoopIndicator count={loopCount} limit={loopLimit} /> : null}
          {index < phases.length - 1 ? <div className="mx-auto h-8 w-px bg-border" /> : null}
        </div>
      ))}
    </div>
  );
}
