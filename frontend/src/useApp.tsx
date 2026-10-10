import { LoadingShell } from "./components/ViewSkeleton";
import {
  Alert,
  Box,
  Button,
  FormControl,
  InputLabel,
  MenuItem,
  Select,
  Stack,
} from "@mui/material";
import { useCallback, useEffect, useId, useRef, useState } from "react";

import { api, errorMessage } from "./api";
import { useFrontendUpdate } from "./frontend-update";
import { useAttention } from "./attention";
import { hasSeen, WELCOME_SEEN, type SettingsSection } from "./onboarding";
import { HelpTip } from "./components/HelpTip";

import { type TourDestination } from "./components/GuidedTour";

import { AuthView } from "./components/AuthView";

import { readLocation, saveLocation, type LocationState } from "./navigation";
import type { AuthState, ProjectRecord } from "./types";
import { type HelpGuide } from "./components/HelpGuides";
import { projectPath as boundProjectPath } from "./navigation";
import {
  loadWorkflowWorkspace,
  SETUP_DISMISSED,
  readSetupDismissed,
} from "./AppShared";
type ReadResponse1 = { run: { project_id: string } };
type ReadResponse2 = { project: ProjectRecord };
type ReadResponse3 = { projects: ProjectRecord[] };
type ReadResponse4 = { run: { project: ProjectRecord } };
type ReadResponse5 = { runs: Array<{ status: string }> };
type ReadResponse6 = { authenticated: boolean };
type ReadResponse7 = { project: ProjectRecord };

export function useApp() {
  const updatedFrontend = useFrontendUpdate();
  const [reloading, setReloading] = useState(false);
  const projectPickerId = useId();
  const [welcomeOpen, setWelcomeOpen] = useState(() => !hasSeen(WELCOME_SEEN));
  const [tourRequested, setTourRequested] = useState(false);
  const [tourSection, setTourSection] = useState<SettingsSection | null>(null);
  const tourReturn = useRef<LocationState | null>(null);
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [location, setLocation] = useState(readLocation);
  const lastSelectedRun = useRef<{ id: string; project: string | null } | null>(
    null,
  );
  useEffect(() => {
    if (location.run)
      lastSelectedRun.current = { id: location.run, project: location.project };
  }, [location.run, location.project]);
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [servedProject, setServedProject] = useState<string | null>(null);
  const [projectReady, setProjectReady] = useState(false);
  const [projectError, setProjectError] = useState<string | null>(null);
  const [openingProject, setOpeningProject] = useState(false);
  const [projectPath, setProjectPath] = useState("");
  const [projectBusy, setProjectBusy] = useState(false);
  const [projectValid, setProjectValid] = useState(false);
  const [authAttempt, setAuthAttempt] = useState(0);
  const [authError, setAuthError] = useState<string | null>(null);
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const [signingOut, setSigningOut] = useState(false);
  const [helpAnchor, setHelpAnchor] = useState<HTMLElement | null>(null);
  useEffect(() => {
    if (!auth?.authenticated) return;
    const timer = window.setTimeout(() => {
      void loadWorkflowWorkspace();
    }, 200);
    return () => window.clearTimeout(timer);
  }, [auth?.authenticated]);
  const [guide, setGuide] = useState<HelpGuide | null>(null);
  const [mobileNav, setMobileNav] = useState<HTMLElement | null>(null);
  const [setupForced, setSetupForced] = useState(false);
  const focusLocation = useRef("");
  const [setupDismissed, setSetupDismissed] = useState(readSetupDismissed);
  const helpButton = useRef<HTMLButtonElement>(null);
  const header = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    const element = header.current;
    if (!element) return;
    const measure = () =>
      document.documentElement.style.setProperty(
        "--relay-header-height",
        `${element.getBoundingClientRect().height}px`,
      );
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => observer.disconnect();
  }, [auth]);
  const setupWasOpen = useRef(false);
  const [setupResult, setSetupResult] = useState<{
    project: string;
    succeeded: boolean;
  } | null>(null);
  const setupRunSucceeded =
    setupResult?.project === location.project &&
    setupResult?.succeeded === true;
  const setupReady =
    setupDismissed ||
    !location.project ||
    setupResult?.project === location.project;
  const [launchWorkflow, setLaunchWorkflow] = useState<string | null>(null);
  const [workflowCreate, setWorkflowCreate] = useState(false);
  const [workflowRevision, setWorkflowRevision] = useState(0);
  const runSucceeded = useCallback(() => {
    const project = currentLocation.current.project;
    if (project) setSetupResult({ project, succeeded: true });
  }, []);
  const beforeLeave = useRef<(() => Promise<void>) | null>(null);
  const registerNavigation = useCallback(
    (callback: (() => Promise<void>) | null) => {
      beforeLeave.current = callback;
    },
    [],
  );

  const historyIntent = useRef<"push" | "replace">("replace");
  const currentLocation = useRef(location);
  currentLocation.current = location;
  const navigationRevision = useRef(0);
  const navigate = useCallback((patch: Partial<LocationState>) => {
    navigationRevision.current += 1;
    historyIntent.current = "push";
    setLocation((current) => ({ ...current, ...patch }));
  }, []);
  const workflowLoaded = useCallback(
    (workflow: string) => {
      setWorkflowCreate(false);
      navigate({ workflow });
    },
    [navigate],
  );
  const navigateSafely = useCallback(
    async (patch: Partial<LocationState>) => {
      try {
        await beforeLeave.current?.();
        navigate(patch);
      } catch (caught) {
        setProjectError(errorMessage(caught));
      }
    },
    [navigate],
  );
  const reloadSafely = useCallback(async () => {
    setReloading(true);
    try {
      await beforeLeave.current?.();
      window.location.reload();
    } catch (caught) {
      setProjectError(errorMessage(caught));
      setReloading(false);
    }
  }, []);
  const showWelcome = useCallback(async () => {
    try {
      await beforeLeave.current?.();
      setWelcomeOpen(true);
    } catch (caught) {
      setProjectError(errorMessage(caught));
    }
  }, []);
  const showTour = useCallback(async () => {
    try {
      await beforeLeave.current?.();
      tourReturn.current = currentLocation.current;
      setTourRequested(true);
    } catch (caught) {
      setProjectError(errorMessage(caught));
    }
  }, []);
  const tourDestination = useCallback(
    async (destination: TourDestination): Promise<void> => {
      if (tourReturn.current === null)
        tourReturn.current = currentLocation.current;
      if (destination.section) {
        setTourSection(destination.section);
        if (currentLocation.current.view !== "settings")
          await navigateSafely({ view: "settings" });
      }
    },
    [navigateSafely],
  );
  const closeTour = useCallback(() => {
    setTourRequested(false);
    setTourSection(null);
    const target = tourReturn.current;
    tourReturn.current = null;
    if (target) void navigateSafely(target);
    helpButton.current?.focus();
  }, [navigateSafely]);
  const selectRun = useCallback((run: string | null) => {
    navigationRevision.current += 1;
    historyIntent.current = "push";
    setLocation((current) => ({
      ...current,
      run,
      interaction: run === current.run ? current.interaction : null,
      job: run === current.run ? current.job : null,
    }));
  }, []);
  async function openWaitingRun(run: string, project?: string): Promise<void> {
    try {
      const projectId =
        project ??
        (await api<ReadResponse1>(`/api/runs/${run}?limit=1`)).run.project_id;
      await navigateSafely({
        view: "runs",
        run,
        project: projectId,
        job: null,
        interaction: null,
      });
    } catch (caught) {
      setProjectError(errorMessage(caught));
    }
  }
  const attention = useAttention(
    auth?.authenticated === true,
    (run, project) => void openWaitingRun(run, project),
  );

  useEffect(() => {
    saveLocation(location, historyIntent.current === "replace");
    historyIntent.current = "replace";
  }, [location]);

  useEffect(() => {
    const restore = () => {
      const target = readLocation();
      const revision = ++navigationRevision.current;
      void (async () => {
        try {
          await beforeLeave.current?.();
          if (revision !== navigationRevision.current) return;
          historyIntent.current = "replace";
          setLocation(target);
        } catch (caught) {
          if (revision !== navigationRevision.current) return;
          saveLocation(currentLocation.current, true);
          setProjectError(errorMessage(caught));
        }
      })();
    };
    window.addEventListener("popstate", restore);
    return () => window.removeEventListener("popstate", restore);
  }, []);

  useEffect(() => {
    if (!auth?.authenticated) return;
    let active = true;
    setProjectReady(false);
    void Promise.all([
      api<ReadResponse2>("/api/projects/current").catch(() => null),
      api<ReadResponse3>("/api/projects"),
      currentLocation.current.run
        ? api<ReadResponse4>(
            `/api/runs/${currentLocation.current.run}?limit=1`,
          ).catch(() => null)
        : Promise.resolve(null),
    ])
      .then(([context, inventory, linkedRun]) => {
        if (!active) return;
        const records = new Map(
          inventory.projects.map((project) => [project.id, project]),
        );
        if (context) records.set(context.project.id, context.project);
        if (linkedRun)
          records.set(linkedRun.run.project.id, linkedRun.run.project);
        setProjects(Array.from(records.values()));
        setServedProject(context?.project.id ?? null);
        setLocation((current) => {
          const remembered =
            current.view === "home" &&
            current.project &&
            !records.has(current.project)
              ? null
              : current.project;
          const next = {
            ...current,
            project:
              linkedRun?.run.project.id ??
              remembered ??
              context?.project.id ??
              inventory.projects[0]?.id ??
              null,
          };
          return next;
        });
        setProjectReady(true);
      })
      .catch((caught: unknown) => {
        if (active) {
          setProjectError(errorMessage(caught));
          setProjectReady(true);
        }
      });
    return () => {
      active = false;
    };
  }, [auth?.authenticated]);

  const selectedProject = projects.find(
    (project) => project.id === location.project,
  );
  const requestProject =
    location.project === servedProject ? null : location.project;
  useEffect(() => {
    setSetupForced(false);
    const project = location.project;
    if (!auth?.authenticated || !project) return;
    const controller = new AbortController();
    void api<ReadResponse5>(
      boundProjectPath(`/api/runs?status=succeeded&limit=1`, project),
      { signal: controller.signal },
    )
      .then((result) => {
        if (!controller.signal.aborted)
          setSetupResult({
            project,
            succeeded: result.runs.length > 0,
          });
      })
      .catch(() => {
        if (!controller.signal.aborted)
          setSetupResult({ project, succeeded: false });
      });
    return () => controller.abort();
  }, [location.project, auth?.authenticated]);
  useEffect(() => {
    if (setupWasOpen.current && !setupForced) helpButton.current?.focus();
    setupWasOpen.current = setupForced;
  }, [setupForced]);

  useEffect(() => {
    const key = `${location.view}:${location.run}:${location.workflow}`;
    const changed = focusLocation.current !== key;
    focusLocation.current = key;
    if (
      !changed ||
      welcomeOpen ||
      openingProject ||
      setupForced ||
      tourRequested
    )
      return;
    const main = document.getElementById("main-content");
    main?.scrollIntoView({ block: "start" });
    main?.focus({ preventScroll: true });
  }, [
    location.view,
    location.run,
    location.workflow,
    welcomeOpen,
    openingProject,
    setupForced,
    tourRequested,
  ]);

  function dismissSetup(): void {
    setSetupDismissed(true);
    try {
      localStorage.setItem(SETUP_DISMISSED, "true");
    } catch {
      /* The current session can dismiss setup when browser storage is unavailable. */
    }
  }

  function openSetup(): void {
    dismissSetup();
    setSetupForced(true);
    setHelpAnchor(null);
  }

  useEffect(() => {
    let active = true;
    setAuthError(null);
    void api<AuthState>("/api/auth")
      .then((value) => {
        if (active) setAuth(value);
      })
      .catch((caught: unknown) => {
        if (active) setAuthError(errorMessage(caught));
      });
    return () => {
      active = false;
    };
  }, [authAttempt]);

  if (auth === null) {
    return {
      fallback: (
        <Box className={authError ? "loading-shell" : undefined}>
          {authError ? (
            <Stack spacing={2} sx={{ maxWidth: 600, p: 2 }}>
              <Alert severity="error">{authError}</Alert>
              <Button
                variant="contained"
                onClick={() => setAuthAttempt((value) => value + 1)}
              >
                Retry
              </Button>
            </Stack>
          ) : (
            <LoadingShell view={location.run ? "summary" : location.view} />
          )}
        </Box>
      ),
    };
  }
  if (!auth.authenticated)
    return { fallback: <AuthView state={auth} onAuthenticated={setAuth} /> };
  const loginRequired = auth.login_required !== false;

  async function logout() {
    setLogoutError(null);
    setSigningOut(true);
    try {
      await beforeLeave.current?.();
      await api<ReadResponse6>("/api/auth/logout", {
        method: "POST",
        body: "{}",
      });
      setAuth(null);
      setAuthAttempt((value) => value + 1);
    } catch (caught) {
      setLogoutError(errorMessage(caught));
    } finally {
      setSigningOut(false);
    }
  }

  async function openProject() {
    setProjectBusy(true);
    setProjectError(null);
    try {
      await beforeLeave.current?.();
      const response = await api<ReadResponse7>("/api/projects/open", {
        method: "POST",
        body: JSON.stringify({ path: projectPath, initialize: true }),
      });
      setProjects((current) => [
        ...current.filter((project) => project.id !== response.project.id),
        response.project,
      ]);
      navigate({
        project: response.project.id,
        workflow: null,
        run: null,
        interaction: null,
        job: null,
        view: "workflows",
      });
      setOpeningProject(false);
    } catch (caught) {
      setProjectError(errorMessage(caught));
    } finally {
      setProjectBusy(false);
    }
  }

  function renderProjectContext() {
    return (
      <Stack
        data-tour="project"
        className="project-context"
        direction="row"
        spacing={1}
        useFlexGap
      >
        {projects.length > 0 && (
          <Box className="project-picker">
            <FormControl fullWidth size="small">
              <InputLabel id={`${projectPickerId}-label`}>Project</InputLabel>
              <Select
                id={projectPickerId}
                labelId={`${projectPickerId}-label`}
                label="Project"
                value={selectedProject?.id ?? ""}
                onChange={(event) =>
                  void navigateSafely({
                    project: event.target.value,
                    view:
                      location.view === "home" ? "workflows" : location.view,
                    workflow: null,
                    run: null,
                    interaction: null,
                    job: null,
                  })
                }
              >
                {projects.map((project) => (
                  <MenuItem key={project.id} value={project.id}>
                    {project.display_name}
                  </MenuItem>
                ))}
              </Select>
            </FormControl>
            <HelpTip topic="project" />
          </Box>
        )}
        <Button onClick={() => setOpeningProject(true)}>
          {projects.length ? "Open another project" : "Open a project"}
        </Button>
      </Stack>
    );
  }
  return {
    fallback: null as null,
    header,
    navigateSafely,
    renderProjectContext,
    location,
    attention,
    mobileNav,
    setMobileNav,
    helpButton,
    loginRequired,
    auth: auth!,
    helpAnchor,
    setHelpAnchor,
    setGuide,
    selectedProject,
    openSetup,
    setOpeningProject,
    showWelcome,
    showTour,
    signingOut,
    logout,
    updatedFrontend,
    reloading,
    reloadSafely,
    projectError,
    openingProject,
    setupDismissed,
    setupRunSucceeded,
    setupReady,
    projectReady,
    dismissSetup,
    setupForced,
    requestProject,
    runSucceeded,
    setSetupForced,
    beforeLeave,
    navigate,
    setWorkflowRevision,
    logoutError,
    setProjects,
    tourSection,
    registerNavigation,
    projects,
    workflowRevision,
    workflowCreate,
    launchWorkflow,
    setLaunchWorkflow,
    workflowLoaded,
    selectRun,
    setWorkflowCreate,
    guide,
    welcomeOpen,
    setWelcomeOpen,
    tourRequested,
    tourDestination,
    closeTour,
    projectBusy,
    projectPath,
    setProjectPath,
    setProjectValid,
    openProject,
    projectValid,
  };
}
export type AppState = Extract<ReturnType<typeof useApp>, { fallback: null }>;
