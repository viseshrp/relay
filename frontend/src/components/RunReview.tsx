import type { ArtifactRecord, RunInteraction } from "../types";

import { useReviewRequest } from "./useReviewRequest";
import { ReviewRequestView } from "./ReviewRequestView";
export { ReviewEvidence } from "./RunReviewShared";
export function ReviewRequest(props: {
  interaction: RunInteraction;
  runId: string;
  artifacts: ArtifactRecord[];
  hasChanges: boolean;
  onLoadAll: () => Promise<void>;
  selected: boolean;
  onAnswered: () => Promise<void>;
}) {
  const state = useReviewRequest(props);
  if (state.fallback !== null) return state.fallback;
  return <ReviewRequestView state={state} />;
}
