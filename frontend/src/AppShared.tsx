import { lazy } from "react";

const SettingsPage = lazy(() =>
  import("./components/SettingsPage").then((module) => ({
    default: module.SettingsPage,
  })),
);
const loadWorkflowWorkspace = () => import("./components/WorkflowWorkspace");
const WorkflowWorkspace = lazy(() =>
  loadWorkflowWorkspace().then((module) => ({
    default: module.WorkflowWorkspace,
  })),
);
const RunWorkspace = lazy(() =>
  import("./components/RunWorkspace").then((module) => ({
    default: module.RunWorkspace,
  })),
);
const SETUP_DISMISSED = "relay.setup-dismissed";
function readSetupDismissed(): boolean {
  try {
    return localStorage.getItem(SETUP_DISMISSED) === "true";
  } catch {
    return false;
  }
}
export {
  SettingsPage,
  loadWorkflowWorkspace,
  WorkflowWorkspace,
  RunWorkspace,
  SETUP_DISMISSED,
  readSetupDismissed,
};
