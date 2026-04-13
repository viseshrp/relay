import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";

import { getPhase, getPrompt } from "@/api/phases";
import type { RunDetail } from "@/types/api";
import { AttemptHistoryTab } from "@/components/detail-panel/AttemptHistoryTab";
import { PhaseLogsTab } from "@/components/detail-panel/PhaseLogsTab";
import { PhasePromptTab } from "@/components/detail-panel/PhasePromptTab";
import { PhaseSummaryTab } from "@/components/detail-panel/PhaseSummaryTab";
import { ReviewCommentsTab } from "@/components/detail-panel/ReviewCommentsTab";
import { WorkflowSummary } from "@/components/detail-panel/WorkflowSummary";
import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";

export function PhaseDetailPanel({
  run,
  selectedPhaseId,
  onRerun,
}: {
  run: RunDetail;
  selectedPhaseId: string | null;
  onRerun: (phaseType: string) => void;
}) {
  const [tab, setTab] = useState("summary");
  const [selectedAttempt, setSelectedAttempt] = useState<number | null>(null);
  const selectedPhase = useMemo(() => run.phases.find((phase) => phase.id === selectedPhaseId) ?? null, [run.phases, selectedPhaseId]);
  const phaseQuery = useQuery({
    queryKey: ["phase", run.id, selectedPhase?.id],
    queryFn: () => getPhase(run.id, selectedPhase!.id),
    enabled: Boolean(selectedPhase),
  });
  const promptQuery = useQuery({
    queryKey: ["prompt", run.id, selectedPhase?.id],
    queryFn: () => getPrompt(run.id, selectedPhase!.id),
    enabled: Boolean(selectedPhase),
  });

  useEffect(() => {
    setTab("summary");
    setSelectedAttempt(null);
  }, [selectedPhaseId]);

  if (!selectedPhase || !phaseQuery.data) {
    return <WorkflowSummary run={run} />;
  }

  const phase = phaseQuery.data;
  const latestAttempt = phase.attempts.find((attempt) => attempt.attempt_number === (selectedAttempt ?? phase.current_attempt)) ?? phase.attempts[phase.attempts.length - 1];

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h2 className="text-2xl font-semibold capitalize">{phase.phase_type.replaceAll("_", " ")}</h2>
          <p className="text-sm text-muted-foreground">Attempt {latestAttempt?.attempt_number ?? 0}</p>
        </div>
        {(phase.status === "failed" || phase.status === "cancelled" || phase.status === "stale") ? (
          <Button variant="secondary" onClick={() => onRerun(phase.phase_type)}>
            Restart from this phase
          </Button>
        ) : null}
      </div>
      <Tabs
        value={tab}
        onValueChange={setTab}
      >
        <TabsList>
          <TabsTrigger value="summary">Summary</TabsTrigger>
          <TabsTrigger value="prompt">Prompt</TabsTrigger>
          <TabsTrigger value="logs">Logs</TabsTrigger>
          {phase.phase_type === "review" ? <TabsTrigger value="review-comments">Review Comments</TabsTrigger> : null}
          <TabsTrigger value="attempts">Attempts</TabsTrigger>
        </TabsList>
        <TabsContent value="summary">
          <PhaseSummaryTab phase={phase} />
        </TabsContent>
        <TabsContent value="prompt">
          <PhasePromptTab prompt={promptQuery.data?.prompt ?? ""} />
        </TabsContent>
        <TabsContent value="logs">
          {latestAttempt ? <PhaseLogsTab runId={run.id} phaseId={phase.id} attemptNumber={latestAttempt.attempt_number} /> : null}
        </TabsContent>
        {phase.phase_type === "review" ? (
          <TabsContent value="review-comments">
            <ReviewCommentsTab comments={latestAttempt?.review_comments ?? []} />
          </TabsContent>
        ) : null}
        <TabsContent value="attempts">
          <AttemptHistoryTab attempts={phase.attempts} onSelect={setSelectedAttempt} />
        </TabsContent>
      </Tabs>
    </div>
  );
}
