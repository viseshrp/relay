import { useEffect, useState } from "react";
import { api, errorMessage } from "../api";
import { projectPath } from "../navigation";
import type {
  LaunchCleanliness,
  OwnerSettings,
  ProjectLaunchSource,
} from "../types";

import { validateLaunchInputs, type LaunchValues } from "./LaunchInputs";

import { LaunchPanelProps } from "./LaunchPanelShared";
type ReadResponse1 = {
  launch_source: ProjectLaunchSource;
  cleanup_policy: OwnerSettings["cleanup_policy"];
};
type ReadResponse2 = { run_id: string };

export function useLaunchPanel({
  open,
  workflowKey,
  workflow,
  project,
  requestProject,
  modelOptions,
  blockedReason,
  saveError,
  onSave,
  onClose,
  onExited,
  onRunLaunched,
  previousRun,
  draftNotice,
  initialEntryPoint = "",
}: LaunchPanelProps) {
  const [inputs, setInputs] = useState<LaunchValues>(previousRun?.inputs ?? {});
  const [model, setModel] = useState("");
  const [cleanup, setCleanup] = useState("");
  const [defaultCleanup, setDefaultCleanup] = useState<
    OwnerSettings["cleanup_policy"] | null
  >(null);
  const [entryPoint, setEntryPoint] = useState("");
  const [source, setSource] = useState<ProjectLaunchSource | null>(null);
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [sourceRevision, setSourceRevision] = useState(0);
  const [launchError, setLaunchError] = useState<string | null>(null);
  const [launching, setLaunching] = useState(false);
  const [preflight, setPreflight] = useState<LaunchCleanliness | null>(null);
  const [preflightError, setPreflightError] = useState<string | null>(null);
  const [inputErrors, setInputErrors] = useState<Record<string, string>>({});

  useEffect(() => {
    if (open) setEntryPoint(initialEntryPoint);
  }, [open, workflowKey, initialEntryPoint]);
  useEffect(() => {
    setInputs(previousRun?.inputs ?? {});
  }, [previousRun]);

  useEffect(() => {
    if (!open) return;
    const controller = new AbortController();
    setSource(null);
    setDefaultCleanup(null);
    setSourceError(null);
    setLaunchError(null);
    void api<ReadResponse1>(
      projectPath("/api/projects/current", requestProject),
      {
        signal: controller.signal,
      },
    )
      .then((response) => {
        if (!controller.signal.aborted) {
          setSource(response.launch_source);
          setDefaultCleanup(response.cleanup_policy);
        }
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) setSourceError(errorMessage(caught));
      });
    return () => controller.abort();
  }, [open, requestProject, sourceRevision]);

  useEffect(() => {
    setPreflight(null);
    setPreflightError(null);
    if (
      !open ||
      workflowKey === null ||
      blockedReason ||
      defaultCleanup === null
    )
      return;
    const controller = new AbortController();
    const path = `/api/workflows/${workflowKey.split("/").map(encodeURIComponent).join("/")}/preflight`;
    const query = `cleanup_policy=${encodeURIComponent(cleanup || defaultCleanup)}`;
    void api<LaunchCleanliness>(
      `${projectPath(path, requestProject)}${requestProject ? "&" : "?"}${query}`,
      { signal: controller.signal },
    )
      .then((result) => {
        if (!controller.signal.aborted) setPreflight(result);
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) setPreflightError(errorMessage(caught));
      });
    return () => controller.abort();
  }, [
    open,
    workflowKey,
    requestProject,
    blockedReason,
    sourceRevision,
    cleanup,
    defaultCleanup,
  ]);

  const reason = launching
    ? "Starting this workflow…"
    : blockedReason ||
      (sourceError
        ? "Relay could not check the current branch. Check again before running."
        : source === null
          ? "Checking the current branch…"
          : source.commit === null
            ? "Create the first Git commit in this project before running a workflow."
            : preflightError
              ? "Fix the project file check, then check again before running."
              : preflight === null
                ? "Checking project files…"
                : !preflight.clean
                  ? `${preflight.blocking_count} ${preflight.blocking_count === 1 ? "file blocks" : "files block"} this run. Commit or set aside the listed changes first.`
                  : null);

  async function launch(): Promise<void> {
    if (reason || workflowKey === null) return;
    const errors = validateLaunchInputs(workflow?.inputs ?? {}, inputs);
    setInputErrors(errors);
    const first = Object.keys(errors)[0];
    if (first) {
      document.getElementById(`launch-input-${first}`)?.focus();
      return;
    }
    setLaunching(true);
    setLaunchError(null);
    try {
      // Untouched values stay omitted so defaults are resolved by the service.
      const supplied = Object.fromEntries(
        Object.entries(inputs).filter(
          ([name, value]) =>
            value !== undefined && Object.hasOwn(workflow?.inputs ?? {}, name),
        ),
      );
      const response = await api<ReadResponse2>(
        projectPath("/api/runs", requestProject),
        {
          method: "POST",
          body: JSON.stringify({
            workflow_key: workflowKey,
            project_id: project.id,
            inputs: supplied,
            ...(model ? { model } : {}),
            ...(cleanup ? { cleanup_policy: cleanup } : {}),
            ...(entryPoint ? { entry_point: entryPoint } : {}),
          }),
        },
      );
      onRunLaunched(response.run_id);
    } catch (caught) {
      setLaunchError(errorMessage(caught));
    } finally {
      setLaunching(false);
    }
  }

  return {
    fallback: null as null,
    open,
    onClose,
    launching,
    onExited,
    launch,
    workflow,
    previousRun,
    draftNotice,
    source,
    cleanup,
    defaultCleanup,
    sourceError,
    reason,
    setSourceRevision,
    blockedReason,
    onSave,
    saveError,
    launchError,
    workflowKey,
    project,
    requestProject,
    preflight,
    preflightError,
    inputs,
    inputErrors,
    setInputs,
    setInputErrors,
    model,
    setModel,
    modelOptions,
    setCleanup,
    entryPoint,
    setEntryPoint,
  };
}
export type LaunchPanelState = Extract<
  ReturnType<typeof useLaunchPanel>,
  { fallback: null }
>;
