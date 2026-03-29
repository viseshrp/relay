import type { PhaseSummary } from "@/types/api";

import { PhaseNode } from "@/components/workflow/PhaseNode";

export function PhaseGraph({
  phases,
  selectedPhaseId,
  onSelect,
}: {
  phases: PhaseSummary[];
  selectedPhaseId: string | null;
  onSelect: (phaseId: string) => void;
}) {
  return (
    <div className="space-y-4">
      {phases.map((phase, index) => (
        <div key={phase.id} className="space-y-4">
          <PhaseNode phase={phase} selected={selectedPhaseId === phase.id} onSelect={() => onSelect(phase.id)} />
          {index < phases.length - 1 ? <div className="mx-auto h-8 w-px bg-border" /> : null}
        </div>
      ))}
    </div>
  );
}
