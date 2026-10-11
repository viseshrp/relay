import { LaunchPanelProps } from "./LaunchPanelShared";
import { useLaunchPanel } from "./useLaunchPanel";
import { LaunchPanelView } from "./LaunchPanelView";
export function LaunchPanel(props: LaunchPanelProps) {
  const state = useLaunchPanel(props);
  if (state.fallback !== null) return state.fallback;
  return <LaunchPanelView state={state} />;
}
