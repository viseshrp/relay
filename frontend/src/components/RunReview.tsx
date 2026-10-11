import type { ArtifactRecord, RunInteraction } from "../types";

import { useReviewRequest } from "./useReviewRequest";
import { ReviewRequestView } from "./ReviewRequestView";
export { ReviewEvidence } from "./RunReviewShared";
export function ReviewRequest(props: {
  interaction: RunInteraction;
  runId: string;
  artifacts: ArtifactRecord[];
  selected: boolean;
  onAnswered: () => Promise<void>;
}) {
  const state = useReviewRequest(props);
  if (state.fallback !== null) return state.fallback;
  return <ReviewRequestView state={state} />;
}
