import type { RunEvent } from "../types";

import { useJobLog } from "./useJobLog";
import { JobLogView } from "./JobLogView";
export function JobLog(props: {
  events: RunEvent[];
  command: boolean;
  label: string;
  workingFolder?: string;
  live: boolean;
  loading: boolean;
  hasMore: boolean;
  onMore: () => Promise<void>;
  onRefresh: () => void;
  scope: string;
  attempt: number | undefined;
}) {
  const state = useJobLog(props);
  if (state.fallback !== null) return state.fallback;
  return <JobLogView state={state} />;
}
