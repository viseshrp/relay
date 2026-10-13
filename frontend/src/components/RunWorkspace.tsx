import { useRunWorkspace } from "./useRunWorkspace";
import { RunReadsContext } from "./RunReadsContext";
import { RunWorkspaceView } from "./RunWorkspaceView";
import type { RunWorkspaceProps } from "./RunWorkspaceShared";
export function RunWorkspace(props: RunWorkspaceProps) {
  const state = useRunWorkspace(props);
  return (
    <RunReadsContext.Provider value={state.readQueue}>
      <RunWorkspaceView state={state} />
    </RunReadsContext.Provider>
  );
}
