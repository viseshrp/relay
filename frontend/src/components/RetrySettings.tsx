import type { RetryConfiguration, RetryOptions } from "../types";
import type { SettingsChoices } from "./usePendingChoices";

import { useRetrySettings } from "./useRetrySettings";
import { RetrySettingsView } from "./RetrySettingsView";
export function RetrySettings(props: {
  problem: RetryConfiguration;
  projectId: string;
  onClose: () => void;
  onRetry: (scope: string, options?: RetryOptions) => Promise<void>;
  purpose?: "retry" | "pending";
  initialChoices?: SettingsChoices;
}) {
  const state = useRetrySettings(props);
  if (state.fallback !== null) return state.fallback;
  return <RetrySettingsView state={state} />;
}
