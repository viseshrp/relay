import type { DashboardRun, ProjectRecord } from "../types";

import { useHomeDashboard } from "./useHomeDashboard";
import { HomeDashboardView } from "./HomeDashboardView";
export function HomeDashboard(props: {
  onOpenProject: () => void;
  onShowWelcome: () => void;
  onNavigate: (
    project: ProjectRecord,
    view: "workflows" | "runs",
    run?: DashboardRun,
  ) => void;
}) {
  const state = useHomeDashboard(props);
  if (state.fallback !== null) return state.fallback;
  return <HomeDashboardView state={state} />;
}
