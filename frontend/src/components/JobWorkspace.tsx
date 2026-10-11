import type { RetryConfiguration, RunEvent, RunNode } from "../types";

import { useJobWorkspace } from "./useJobWorkspace";
import { JobWorkspaceView } from "./JobWorkspaceView";
export function JobWorkspace(props: {
  runId: string;
  scope: string;
  nodes: RunNode[];
  embedded?: boolean;
  liveEvents: RunEvent[];
  canRetry: boolean;
  refreshing: boolean;
  onRetry: (scope: string) => Promise<void>;
  onRetrySettings: (settings: RetryConfiguration) => void;
}) {
  const state = useJobWorkspace(props);
  if (state.fallback !== null) return state.fallback;
  return <JobWorkspaceView state={state} />;
}
