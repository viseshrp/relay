import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useParams } from "react-router-dom";

import {
  advanceRun,
  approveReview,
  cancelRun,
  getExplorationContext,
  rerunRun,
  sendReviewFix,
  updateExplorationContext,
} from "@/api/exploration";
import { getRun } from "@/api/runs";
import { ChatInput } from "@/components/exploration/ChatInput";
import { ChatThread } from "@/components/exploration/ChatThread";
import { ContextPanel } from "@/components/exploration/ContextPanel";
import { FinalizeButton } from "@/components/exploration/FinalizeButton";
import { PlanningPromptView } from "@/components/exploration/PlanningPromptView";
import { PhaseDetailPanel } from "@/components/detail-panel/PhaseDetailPanel";
import { ReviewApprovalBar } from "@/components/review/ReviewApprovalBar";
import { FixPromptEditor } from "@/components/review/FixPromptEditor";
import { PhaseGraph } from "@/components/workflow/PhaseGraph";
import { ReviewFixLoopIndicator } from "@/components/workflow/ReviewFixLoopIndicator";
import { Button } from "@/components/ui/button";
import { useExplorationChat } from "@/hooks/useExplorationChat";
import { useRunStatus } from "@/hooks/useRunStatus";
import { useRunStore } from "@/store/runStore";

export function RunDetailPage() {
  const { id = "" } = useParams();
  const queryClient = useQueryClient();
  const [contextOpen, setContextOpen] = useState(false);
  const [fixPromptOpen, setFixPromptOpen] = useState(false);
  const selectedPhaseId = useRunStore((state) => state.selectedPhaseId);
  const setSelectedPhaseId = useRunStore((state) => state.setSelectedPhaseId);
  const runQuery = useQuery({ queryKey: ["run", id], queryFn: () => getRun(id), refetchInterval: 4000 });
  const contextQuery = useQuery({ queryKey: ["context", id], queryFn: () => getExplorationContext(id), enabled: Boolean(id) });
  const planningPromptQuery = useQuery({
    queryKey: ["planning-prompt", id],
    queryFn: async () => {
      const response = await fetch(`/api/v1/runs/${id}/artifacts/exploration/planning_prompt.md`);
      return response.ok ? await response.text() : "";
    },
    enabled: Boolean(id),
  });
  const { messages, isStreaming, sendMessage, finalize } = useExplorationChat(id);
  useRunStatus(id);

  useEffect(() => {
    if (!runQuery.data || selectedPhaseId) {
      return;
    }
    setSelectedPhaseId(runQuery.data.phases[0]?.id ?? null);
  }, [runQuery.data, selectedPhaseId, setSelectedPhaseId]);

  const currentRun = runQuery.data;
  const selectedPhase = useMemo(() => currentRun?.phases.find((phase) => phase.id === selectedPhaseId) ?? null, [currentRun, selectedPhaseId]);
  const explorationPhase = currentRun?.phases.find((phase) => phase.phase_type === "exploration");
  const critiquePhase = currentRun?.phases.find((phase) => phase.phase_type === "plan_critique");
  const reviewPhase = currentRun?.phases.find((phase) => phase.phase_type === "review");
  const showExploration = Boolean(explorationPhase && ["queued", "running", "waiting_for_user"].includes(explorationPhase.status));

  const contextMutation = useMutation({
    mutationFn: (paths: string[]) => updateExplorationContext(id, paths),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["context", id] }),
  });
  const rerunMutation = useMutation({
    mutationFn: (phaseType: string) => rerunRun(id, phaseType),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["run", id] }),
  });

  if (!currentRun) {
    return null;
  }

  return (
    <div className="grid gap-6 lg:grid-cols-[24rem,minmax(0,1fr)]">
      <div className="space-y-4">
        <ReviewFixLoopIndicator count={currentRun.review_fix_loop_count} limit={currentRun.review_fix_loop_limit} />
        <PhaseGraph phases={currentRun.phases} selectedPhaseId={selectedPhaseId} onSelect={setSelectedPhaseId} />
      </div>
      <div className="space-y-4">
        {showExploration && selectedPhase?.phase_type === "exploration" ? (
          <>
            <div className="flex items-center justify-between gap-3">
              <div>
                <h1 className="text-3xl font-semibold">Exploration</h1>
                <p className="text-sm text-muted-foreground">Interactive discovery before planning starts.</p>
              </div>
              <div className="flex gap-3">
                <Button variant="secondary" onClick={() => setContextOpen(true)}>
                  Context
                </Button>
                <FinalizeButton disabled={isStreaming} onFinalize={finalize} />
              </div>
            </div>
            <ChatThread messages={messages} />
            <ChatInput disabled={isStreaming || explorationPhase?.status === "waiting_for_user"} onSend={sendMessage} />
            {explorationPhase?.status === "waiting_for_user" ? (
              <div className="flex flex-wrap gap-3">
                <Button onClick={() => void advanceRun(id).then(() => queryClient.invalidateQueries({ queryKey: ["run", id] }))}>Start Planning</Button>
                <PlanningPromptView content={planningPromptQuery.data ?? ""} />
              </div>
            ) : null}
            <ContextPanel
              open={contextOpen}
              onOpenChange={setContextOpen}
              projectId={currentRun.project_id}
              selected={contextQuery.data?.context_paths ?? []}
              onToggle={(path) => {
                const current = contextQuery.data?.context_paths ?? [];
                const next = current.includes(path) ? current.filter((item) => item !== path) : [...current, path];
                contextMutation.mutate(next);
              }}
            />
          </>
        ) : (
          <PhaseDetailPanel run={currentRun} selectedPhaseId={selectedPhaseId} onRerun={(phaseType) => rerunMutation.mutate(phaseType)} />
        )}

        {currentRun.status === "waiting_for_user" && critiquePhase?.status === "waiting_for_user" ? (
          <Button onClick={() => void advanceRun(id).then(() => queryClient.invalidateQueries({ queryKey: ["run", id] }))}>
            Continue to Plan Correction
          </Button>
        ) : null}

        {currentRun.status === "waiting_for_user" && reviewPhase?.status === "waiting_for_user" ? (
          <>
            <ReviewApprovalBar
              onApprove={async () => {
                await approveReview(id);
                await queryClient.invalidateQueries({ queryKey: ["run", id] });
              }}
              onFix={() => setFixPromptOpen(true)}
              onCancel={async () => {
                await cancelRun(id);
                await queryClient.invalidateQueries({ queryKey: ["run", id] });
              }}
            />
            <FixPromptEditor
              open={fixPromptOpen}
              initialValue=""
              onOpenChange={setFixPromptOpen}
              onSubmit={async (value) => {
                await sendReviewFix(id, value);
                setFixPromptOpen(false);
                await queryClient.invalidateQueries({ queryKey: ["run", id] });
              }}
            />
          </>
        ) : null}
      </div>
    </div>
  );
}
