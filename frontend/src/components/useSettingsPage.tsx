import { ViewSkeleton } from "./ViewSkeleton";
import { settingsErrors } from "../settings-validation";

import { Alert, Box, Button, Stack } from "@mui/material";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, errorMessage } from "../api";
import { projectPath } from "../navigation";
import type {
  AgentsResponse,
  OwnerSettings,
  ProjectDefaultOverrides,
  ProjectSettingsResponse,
  SettingsResponse,
} from "../types";

import { Section, Props } from "./SettingsPageShared";
type ReadResponse1 = { effective: OwnerSettings };
type ReadResponse2 = { effective: OwnerSettings };

export function useSettingsPage({
  project,
  requestProject,
  notifications,
  onToggleNotifications,
  onNavigationReady,
  tourSection,
  onShowWelcome,
  onShowTour,
  onResetOnboarding,
}: Props) {
  const [onboardingNotice, setOnboardingNotice] = useState<string | null>(null);
  const [pendingSection, setPendingSection] = useState<Section | null>(null);
  const [section, setSection] = useState<Section>("Global defaults");
  useEffect(() => {
    if (tourSection) setSection(tourSection);
  }, [tourSection]);
  const [response, setResponse] = useState<SettingsResponse | null>(null);
  const [draft, setDraft] = useState<OwnerSettings | null>(null);
  const [agents, setAgents] = useState<AgentsResponse | null>(null);
  const [projectResponse, setProjectResponse] =
    useState<ProjectSettingsResponse | null>(null);
  const [overrides, setOverrides] = useState<ProjectDefaultOverrides>({});
  const [effective, setEffective] = useState<OwnerSettings | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const [revision, setRevision] = useState(0);
  const preview = useRef<AbortController | null>(null);
  const heading = useRef<HTMLHeadingElement | null>(null);
  const previousSection = useRef(section);
  useEffect(() => {
    if (loading || section === previousSection.current) return;
    previousSection.current = section;
    heading.current?.scrollIntoView({ block: "start" });
    if (!tourSection) heading.current?.focus({ preventScroll: true });
  }, [section, loading, tourSection]);
  const projectId = project?.id;
  const dirty =
    Boolean(
      response &&
      draft &&
      JSON.stringify(response.settings) !== JSON.stringify(draft),
    ) ||
    Boolean(
      projectResponse &&
      JSON.stringify(projectResponse.overrides) !== JSON.stringify(overrides),
    );

  const preventLeave = useCallback(async () => {
    if (dirty) throw new Error("Save or discard your settings before leaving.");
  }, [dirty]);
  useEffect(() => {
    onNavigationReady(preventLeave);
    return () => onNavigationReady(null);
  }, [onNavigationReady, preventLeave]);
  useEffect(() => {
    const warn = (event: BeforeUnloadEvent) => {
      if (dirty) event.preventDefault();
    };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError(null);
    setNotice(null);
    void Promise.allSettled([
      api<SettingsResponse>("/api/settings", { signal: controller.signal }),
      api<AgentsResponse>(projectPath("/api/agents", requestProject), {
        signal: controller.signal,
      }),
      projectId
        ? api<ProjectSettingsResponse>(
            projectPath("/api/projects/defaults", requestProject),
            { signal: controller.signal },
          )
        : Promise.resolve(null),
    ])
      .then(([global, tools, local]) => {
        if (controller.signal.aborted) return;
        if (global.status === "rejected") {
          setResponse(null);
          setDraft(null);
          setError(errorMessage(global.reason));
          return;
        }
        const projectSettings =
          local.status === "fulfilled" ? local.value : null;
        setResponse(global.value);
        setDraft(global.value.settings);
        setAgents(tools.status === "fulfilled" ? tools.value : null);
        setProjectResponse(projectSettings);
        setOverrides(projectSettings?.overrides ?? {});
        setEffective(projectSettings?.effective ?? null);
        const failures = [tools, local].filter(
          (result) => result.status === "rejected",
        );
        setError(
          failures
            .map((result) =>
              result.status === "rejected" ? errorMessage(result.reason) : "",
            )
            .join(" ") || null,
        );
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) setError(errorMessage(caught));
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => {
      controller.abort();
      preview.current?.abort();
    };
  }, [projectId, requestProject, revision]);

  function updateOverrides(values: ProjectDefaultOverrides) {
    setOverrides(values);
    setNotice(null);
    setError(null);
    preview.current?.abort();
    const merged = effective && {
      ...effective,
      ...values,
      workflow_defaults: {
        ...effective.workflow_defaults,
        ...values.workflow_defaults,
        recovery: {
          ...effective.workflow_defaults.recovery,
          ...values.workflow_defaults?.recovery,
        },
        repairs: {
          ...effective.workflow_defaults.repairs,
          ...values.workflow_defaults?.repairs,
        },
      },
    };
    if (merged && Object.keys(settingsErrors(merged)).length) return;
    const controller = new AbortController();
    preview.current = controller;
    void api<ReadResponse1>(
      projectPath("/api/projects/defaults", requestProject),
      {
        method: "POST",
        signal: controller.signal,
        body: JSON.stringify({ overrides: values, preview: true }),
      },
    )
      .then((result) => {
        if (!controller.signal.aborted) setEffective(result.effective);
      })
      .catch((caught: unknown) => {
        if (!controller.signal.aborted) setError(errorMessage(caught));
      });
  }
  async function save(projectOnly = false): Promise<void> {
    if (
      !draft ||
      !response ||
      Object.keys(settingsErrors(projectOnly && effective ? effective : draft))
        .length
    )
      return;
    setBusy(true);
    setError(null);
    setNotice(null);
    preview.current?.abort();
    try {
      if (projectOnly && projectResponse) {
        const result = await api<ProjectSettingsResponse>(
          projectPath("/api/projects/defaults", requestProject),
          {
            method: "POST",
            body: JSON.stringify({
              overrides,
              revision: projectResponse.revision,
            }),
          },
        );
        setProjectResponse(result);
        setOverrides(result.overrides);
        setEffective(result.effective);
        setNotice("Project defaults saved. Future runs inherit these choices.");
      } else {
        const result = await api<SettingsResponse>("/api/settings", {
          method: "POST",
          body: JSON.stringify({
            settings: draft,
            revision: response.revision,
          }),
        });
        const restart = ["host", "port", "workers", "login_required"] as const;
        const changed = restart.some(
          (key) => result.settings[key] !== response.settings[key],
        );
        setResponse(result);
        setDraft(result.settings);
        setNotice(
          changed
            ? "Settings saved. Restart Relay to apply server and login changes."
            : "Global defaults saved. Future runs inherit these choices.",
        );
        if (project) {
          const local = await api<ProjectSettingsResponse>(
            projectPath("/api/projects/defaults", requestProject),
          );
          setProjectResponse(local);
          if (
            projectResponse &&
            JSON.stringify(projectResponse.overrides) !==
              JSON.stringify(overrides)
          ) {
            const pending = await api<ReadResponse2>(
              projectPath("/api/projects/defaults", requestProject),
              {
                method: "POST",
                body: JSON.stringify({ overrides, preview: true }),
              },
            );
            setEffective(pending.effective);
          } else setEffective(local.effective);
        }
      }
    } catch (caught) {
      setError(errorMessage(caught));
    } finally {
      setBusy(false);
    }
  }
  function discard() {
    setDraft(response?.settings ?? null);
    setOverrides(projectResponse?.overrides ?? {});
    setEffective(projectResponse?.effective ?? null);
    setNotice(null);
    setError(null);
    preview.current?.abort();
  }

  if (loading)
    return {
      fallback: <ViewSkeleton view="settings" />,
    };
  if (!response || !draft)
    return {
      fallback: (
        <Stack spacing={2}>
          <Alert severity="error">
            {error ?? "Settings could not be loaded."}
          </Alert>
          <Button onClick={() => setRevision((value) => value + 1)}>
            Retry settings
          </Button>
        </Stack>
      ),
    };
  const fieldErrors = settingsErrors(
    section === "Project defaults" && effective ? effective : draft,
  );
  const projectView = section === "Project defaults";
  const editable =
    section === "Global defaults" ||
    projectView ||
    section === "Server and account";

  return {
    fallback: null as null,
    section,
    dirty,
    setPendingSection,
    setSection,
    setNotice,
    setError,
    heading,
    projectView,
    project,
    error,
    busy,
    setRevision,
    notice,
    draft: draft!,
    agents,
    setDraft,
    requestProject,
    tourSection,
    effective,
    setEffective,
    overrides,
    updateOverrides,
    response: response!,
    fieldErrors,
    notifications,
    onToggleNotifications,
    onShowWelcome,
    onShowTour,
    setOnboardingNotice,
    onResetOnboarding,
    onboardingNotice,
    editable,
    projectResponse,
    save,
    discard,
    pendingSection,
  };
}
export type SettingsPageState = Extract<
  ReturnType<typeof useSettingsPage>,
  { fallback: null }
>;
