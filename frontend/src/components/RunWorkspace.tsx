import { useRunWorkspace } from "./useRunWorkspace";
import { RunWorkspaceView } from "./RunWorkspaceView";
import type { RunWorkspaceProps } from "./RunWorkspaceShared";
export function RunWorkspace(props: RunWorkspaceProps) {
  const state = useRunWorkspace(props);
  return <RunWorkspaceView state={state} />;
}
