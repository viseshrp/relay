import {
  AppBar, Alert, Box, Button, CircularProgress, Container, Dialog,
  DialogActions, DialogContent, DialogTitle, Divider, MenuItem, Menu,
  Stack, Tab, Tabs, Toolbar, Typography } from "@mui/material";
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";
import { WorkspaceBoundary } from "./components/WorkspaceBoundary";

import { api, errorMessage } from "./api";
import { useAttention } from "./attention";
import { hasSeen, TOUR_SEEN, WELCOME_SEEN, resetOnboarding, type SettingsSection } from "./onboarding";
import { HelpTextField, HelpSelectField } from "./components/HelpTip";
import { WelcomeCarousel } from "./components/WelcomeCarousel";
import { GuidedTour, type TourDestination } from "./components/GuidedTour";
import { GettingStartedHome } from "./components/GettingStartedHome";
import { HomeDashboard } from "./components/HomeDashboard";
import { ActionIcon } from "./components/ActionIcon";
import { AuthView } from "./components/AuthView";
import { GetStarted } from "./components/GetStarted";
import { FolderPicker } from "./components/FolderPicker";
import { readLocation, saveLocation, type LocationState } from "./navigation";
import type { AuthState, ProjectRecord } from "./types";

const SettingsPage = lazy(() => import("./components/SettingsPage").then((module) => ({ default: module.SettingsPage })));

const WorkflowWorkspace = lazy(() =>
  import("./components/WorkflowWorkspace").then((module) => ({
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
  try { return localStorage.getItem(SETUP_DISMISSED) === "true"; }
  catch { return false; }
}

export function App() {
  const [welcomeOpen, setWelcomeOpen] = useState(() => !hasSeen(WELCOME_SEEN));
  const [tourRequested, setTourRequested] = useState(() => !hasSeen(TOUR_SEEN));
  const [tourSection, setTourSection] = useState<SettingsSection | null>(null);
  const tourReturn = useRef<LocationState | null>(null);
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [location, setLocation] = useState(readLocation);
  const lastSelectedRun = useRef<{ id: string; project: string | null } | null>(null);
  useEffect(() => {
    if (location.run) lastSelectedRun.current = { id: location.run, project: location.project };
  }, [location.run, location.project]);
  const [projects, setProjects] = useState<ProjectRecord[]>([]);
  const [servedProject, setServedProject] = useState<string | null>(null);
  const [projectReady, setProjectReady] = useState(false);
  const [projectError, setProjectError] = useState<string | null>(null);
  const [openingProject, setOpeningProject] = useState(false);
  const [projectPath, setProjectPath] = useState("");
  const [projectBusy, setProjectBusy] = useState(false);
  const [authAttempt, setAuthAttempt] = useState(0);
  const [authError, setAuthError] = useState<string | null>(null);
  const [logoutError, setLogoutError] = useState<string | null>(null);
  const [signingOut, setSigningOut] = useState(false);
  const [helpAnchor, setHelpAnchor] = useState<HTMLElement | null>(null);
  const [setupForced, setSetupForced] = useState(false);
  const [setupDismissed, setSetupDismissed] = useState(readSetupDismissed);
  const helpButton = useRef<HTMLButtonElement>(null);
  const setupWasOpen = useRef(false);
  const [setupRunSucceeded, setSetupRunSucceeded] = useState(false);
  const [launchWorkflow, setLaunchWorkflow] = useState<string | null>(null);
  const [workflowCreate, setWorkflowCreate] = useState(false);
  const [workflowRevision, setWorkflowRevision] = useState(0);
  const runSucceeded = useCallback(() => setSetupRunSucceeded(true), []);
  const beforeLeave = useRef<(() => Promise<void>) | null>(null);
  const registerNavigation = useCallback((callback: (() => Promise<void>) | null) => { beforeLeave.current = callback; }, []);

  const historyIntent = useRef<"push" | "replace">("replace");
  const currentLocation = useRef(location);
  currentLocation.current = location;
  const navigationRevision = useRef(0);
  const navigate = useCallback((patch: Partial<LocationState>) => {
    navigationRevision.current += 1;
    historyIntent.current = "push";
    setLocation((current) => ({ ...current, ...patch }));
  }, []);
  const workflowLoaded = useCallback((workflow: string) => { setWorkflowCreate(false); navigate({ workflow }); }, [navigate]);
  const navigateSafely = useCallback(async (patch: Partial<LocationState>) => {
    try { await beforeLeave.current?.(); navigate(patch); }
    catch (caught) { setProjectError(errorMessage(caught)); }
  }, [navigate]);
  const showWelcome = useCallback(async () => {
    try { await beforeLeave.current?.(); setWelcomeOpen(true); }
    catch (caught) { setProjectError(errorMessage(caught)); }
  }, []);
  const showTour = useCallback(async () => {
    try { await beforeLeave.current?.(); tourReturn.current = currentLocation.current; setTourRequested(true); }
    catch (caught) { setProjectError(errorMessage(caught)); }
  }, []);
  const tourDestination = useCallback((destination: TourDestination) => {
    if (tourReturn.current === null) tourReturn.current = currentLocation.current;
    if (destination.section) {
      setTourSection(destination.section);
      if (currentLocation.current.view !== "settings") void navigateSafely({ view: "settings" });
    }
  }, [navigateSafely]);
  const closeTour = useCallback(() => {
    setTourRequested(false); setTourSection(null);
    const target = tourReturn.current; tourReturn.current = null;
    if (target) void navigateSafely(target);
    helpButton.current?.focus();
  }, [navigateSafely]);
  const selectRun = useCallback((run: string | null) => {
    navigationRevision.current += 1;
    historyIntent.current = "push";
    setLocation((current) => ({ ...current, run, interaction: run === current.run ? current.interaction : null, job: run === current.run ? current.job : null }));
  }, []);
  async function openWaitingRun(run: string, project?: string): Promise<void> {
    try {
      const projectId = project ?? (await api<{ run: { project_id: string } }>(`/api/runs/${run}?limit=1`)).run.project_id;
      await navigateSafely({ view: "runs", run, project: projectId, job: null, interaction: null });
    } catch (caught) { setProjectError(errorMessage(caught)); }
  }
  const attention = useAttention(auth?.authenticated === true, (run, project) => void openWaitingRun(run, project));

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
      api<{ project: ProjectRecord }>("/api/projects/current").catch(() => null),
      api<{ projects: ProjectRecord[] }>("/api/projects"),
      location.run ? api<{ run: { project: ProjectRecord } }>(`/api/runs/${location.run}?limit=1`).catch(() => null) : Promise.resolve(null),
    ]).then(([context, inventory, linkedRun]) => {
      if (!active) return;
      const records = new Map(inventory.projects.map((project) => [project.id, project]));
      if (context) records.set(context.project.id, context.project);
      if (linkedRun) records.set(linkedRun.run.project.id, linkedRun.run.project);
      setProjects(Array.from(records.values()));
      setServedProject(context?.project.id ?? null);
      setLocation((current) => {
        const remembered = current.view === "home" && current.project && !records.has(current.project) ? null : current.project;
        const next = { ...current, project: linkedRun?.run.project.id ?? remembered ?? context?.project.id ?? inventory.projects[0]?.id ?? null };
        return next;
      });
      setProjectReady(true);
    }).catch((caught: unknown) => { if (active) { setProjectError(errorMessage(caught)); setProjectReady(true); } });
    return () => { active = false; };
  }, [auth?.authenticated]);

  const selectedProject = projects.find((project) => project.id === location.project);
  const requestProject = location.project === servedProject ? null : location.project;
  useEffect(() => { setSetupRunSucceeded(false); setSetupForced(false); }, [location.project]);
  useEffect(() => {
    if (setupWasOpen.current && !setupForced) helpButton.current?.focus();
    setupWasOpen.current = setupForced;
  }, [setupForced]);

  function dismissSetup(): void {
    setSetupDismissed(true);
    try { localStorage.setItem(SETUP_DISMISSED, "true"); }
    catch { /* The current session can dismiss setup when browser storage is unavailable. */ }
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
      .then((value) => { if (active) setAuth(value); })
      .catch((caught: unknown) => { if (active) setAuthError(errorMessage(caught)); });
    return () => { active = false; };
  }, [authAttempt]);

  if (auth === null) {
    return (
      <Box className="loading-shell">
        {authError ? (
          <Stack spacing={2} sx={{ maxWidth: 600, p: 2 }}>
            <Alert severity="error">{authError}</Alert>
            <Button variant="contained" onClick={() => setAuthAttempt((value) => value + 1)}>
              Retry
            </Button>
          </Stack>
        ) : <CircularProgress aria-label="Loading Relay" />}
      </Box>
    );
  }
  if (!auth.authenticated) return <AuthView state={auth} onAuthenticated={setAuth} />;
  const loginRequired = auth.login_required !== false;

  async function logout() {
    setLogoutError(null);
    setSigningOut(true);
    try {
      await beforeLeave.current?.();
      await api<{ authenticated: boolean }>("/api/auth/logout", {
        method: "POST", body: "{}",
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
      const response = await api<{ project: ProjectRecord }>("/api/projects/open", {
        method: "POST", body: JSON.stringify({ path: projectPath, initialize: true }),
      });
      setProjects((current) => [...current.filter((project) => project.id !== response.project.id), response.project]);
      navigate({ project: response.project.id, workflow: null, run: null, interaction: null, job: null, view: "workflows" });
      setOpeningProject(false);
    } catch (caught) {
      setProjectError(errorMessage(caught));
    } finally {
      setProjectBusy(false);
    }
  }

  return (
    <Box sx={{ minHeight: "100vh" }}>
      <AppBar position="sticky" color="inherit" elevation={0} className="app-header">
        <Toolbar>
          <Button component="a" href="/?view=home" aria-label="Relay home" className="relay-home-link" onClick={(event) => {
            if (event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
            event.preventDefault(); void navigateSafely({ view: "home", workflow: null, run: null, job: null, interaction: null });
          }}>Relay</Button>
          {renderProjectContext()}
          <Tabs
            value={location.view === "home" || (loginRequired && location.view === "settings") ? false : location.view}
            onChange={(_event, value: LocationState["view"]) => {
              const previousRun = lastSelectedRun.current?.project === location.project ? lastSelectedRun.current.id : null;
              const selected = location.run ?? previousRun;
              const waiting = selected && attention.attention.waiting_runs.includes(selected) ? selected : attention.attention.waiting_runs[0];
              if (value === "runs" && waiting && location.view !== "runs") void openWaitingRun(waiting);
              else void navigateSafely({ view: value, run: null, job: null, interaction: null });
            }}
            sx={{ flex: 1, minWidth: 270 }}
          >
            {!loginRequired && <Tab data-tour="settings-tab" value="settings" label="Settings" sx={{ order: 3 }} />}
            <Tab data-tour="workflow-tab" value="workflows" label="Workflows" />
            <Tab data-tour="runs-tab" value="runs" label={attention.attention.waiting_count ? `Runs (${attention.attention.waiting_count})` : "Runs"} />
          </Tabs>
          <Button ref={helpButton} aria-label={loginRequired ? `Account menu for ${auth.username}` : "Help"} aria-haspopup="menu" aria-expanded={helpAnchor !== null} endIcon={<ActionIcon name="down" />} onClick={(event) => setHelpAnchor(event.currentTarget)}>{loginRequired ? auth.username : "Help"}</Button>
          <Menu anchorEl={helpAnchor} open={helpAnchor !== null} onClose={() => setHelpAnchor(null)}>
            {loginRequired && <MenuItem onClick={() => { setHelpAnchor(null); void navigateSafely({ view: "settings", run: null, job: null, interaction: null }); }}>Settings</MenuItem>}
            {loginRequired && <Divider />}
            <MenuItem onClick={selectedProject ? openSetup : () => { setHelpAnchor(null); setOpeningProject(true); }}>Get started</MenuItem>
            <MenuItem onClick={() => { setHelpAnchor(null); void showWelcome(); }}>Welcome slides</MenuItem>
            <MenuItem onClick={() => { setHelpAnchor(null); void showTour(); }}>Guided tour</MenuItem>
            <MenuItem onClick={() => { void attention.toggleNotifications(); setHelpAnchor(null); }}>{attention.notifications ? "Disable desktop notifications" : "Enable desktop notifications"}</MenuItem>
            {loginRequired && <Divider />}
            {loginRequired && <MenuItem disabled={signingOut} onClick={() => { setHelpAnchor(null); void logout(); }}>Sign out</MenuItem>}
          </Menu>
        </Toolbar>
      </AppBar>
      <Container maxWidth={false} className="app-content">

        {attention.error && <Alert severity="warning" sx={{ mb: 2 }}>{attention.error}</Alert>}
        {projectError && !openingProject && <Alert severity="error" sx={{ mb: 2 }}>{projectError}</Alert>}
        {!setupDismissed && <Alert className="setup-banner" severity="info" role="region" aria-label="Welcome to Relay" sx={{ mb: 2 }} action={
          <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: "wrap" }}>
            <Button onClick={openSetup} disabled={!projectReady || !selectedProject}>Get started</Button>
            <Button onClick={dismissSetup}>Dismiss welcome</Button>
          </Stack>
        }>New to Relay? Check agents and choose your first workflow.</Alert>}
        {setupForced && projectReady && selectedProject && <GetStarted key={selectedProject.id} project={selectedProject} requestProject={requestProject}
          runSucceeded={setupRunSucceeded} onClose={() => setSetupForced(false)} onOpenProject={() => { setSetupForced(false); setOpeningProject(true); }}
          onWorkflowCreated={async (key) => {
            await beforeLeave.current?.();
            navigate({ workflow: key, view: "workflows", run: null, interaction: null, job: null });
            setWorkflowRevision((value) => value + 1);
          }} onRunLaunched={(id) => { setSetupForced(false); navigate({ run: id, interaction: null, job: null, view: "runs" }); }} />}
        {logoutError && (
          <Alert severity="error" sx={{ mb: 2 }} action={
            <Button color="inherit" onClick={() => void logout()} disabled={signingOut}>Retry</Button>
          }>{logoutError}</Alert>
        )}
        <WorkspaceBoundary><Suspense fallback={<Box className="loading-panel"><CircularProgress /></Box>}>
          {!projectReady ? <Box className="loading-panel"><CircularProgress aria-label="Loading projects" /></Box>
          : location.view === "home" ? <HomeDashboard onOpenProject={() => setOpeningProject(true)} onShowWelcome={() => void showWelcome()} onNavigate={(project, view, run) => {
            setProjects((current) => [...current.filter((value) => value.id !== project.id), project]);
            void navigateSafely({ project: project.id, view, workflow: null, run: run?.id ?? null, job: null, interaction: run?.request?.id ?? null });
          }} />
          : location.view === "settings" ? <SettingsPage tourSection={tourSection} onShowWelcome={() => void showWelcome()} onShowTour={() => void showTour()} onResetOnboarding={resetOnboarding} project={selectedProject} requestProject={requestProject} notifications={attention.notifications} onToggleNotifications={attention.toggleNotifications} onNavigationReady={registerNavigation} />
          : projects.length === 0 && !projectError ? <GettingStartedHome onOpenProject={() => setOpeningProject(true)} onShowWelcome={() => void showWelcome()} />
          : !selectedProject ? <Alert severity="info">Choose a project above, or open a Git repository to begin.</Alert>
          : location.view === "workflows" ? (
            <WorkflowWorkspace
              key={`${selectedProject.id}-${workflowRevision}`}
              project={selectedProject}
              requestProject={requestProject}
              initialCreate={workflowCreate}
              initialWorkflow={location.workflow}
              initialLaunch={launchWorkflow === location.workflow && launchWorkflow !== null}
              onLaunchClosed={() => setLaunchWorkflow(null)}
              onWorkflowLoaded={workflowLoaded}
              onNavigationReady={registerNavigation}
              onRunLaunched={(runId) => {
                setLaunchWorkflow(null);
                navigate({ run: runId, interaction: null, job: null, view: "runs" });
              }}
            />
          ) : (
            <RunWorkspace
              selectedRun={location.run}
              selectedWorkflow={location.workflow}
              onSelectWorkflow={(workflow) => navigate({ workflow })}
              project={selectedProject}
              selectedInteraction={location.interaction}
              selectedJob={location.job}
              waitingRuns={attention.attention.waiting_runs}
              onSelectJob={(job) => navigate({ job })}
              onRunSucceeded={runSucceeded}
              onSelectRun={selectRun}
              onEditWorkflow={(workflow) => { setWorkflowCreate(!workflow); setWorkflowRevision((value) => value + 1); navigate({ workflow: workflow || null, view: "workflows", run: null, interaction: null, job: null }); }}
              onRunWorkflow={(workflow) => {
                setLaunchWorkflow(workflow);
                navigate({ workflow, view: "workflows", run: null, interaction: null, job: null });
              }}
            />
          )}
        </Suspense></WorkspaceBoundary>
      </Container>
      {projectReady && welcomeOpen && <WelcomeCarousel onClose={() => { dismissSetup(); setWelcomeOpen(false); helpButton.current?.focus(); }} onShowTour={() => { dismissSetup(); setWelcomeOpen(false); void showTour(); }} />}
      {projectReady && !welcomeOpen && !openingProject && !setupForced && tourRequested && <GuidedTour onDestination={tourDestination} onClose={closeTour} />}
      <Dialog open={openingProject} onClose={() => !projectBusy && setOpeningProject(false)} fullWidth>
        <DialogTitle>Open a project</DialogTitle>
        <DialogContent>
          <Typography sx={{ mb: 2 }}>Choose a Git repository on this computer. Relay adds a blank workflow folder if one is missing. Your code and Git branch stay in place.</Typography>
          <HelpTextField topic="project" label="Repository folder" fullWidth value={projectPath} onChange={(event) => setProjectPath(event.target.value)} placeholder="/path/to/project"  />
          <Box sx={{ mt: 2 }}><FolderPicker disabled={projectBusy} onSelect={setProjectPath} /></Box>
          {projectError && <Alert severity="error" sx={{ mt: 2 }}>{projectError}</Alert>}
        </DialogContent>
        <DialogActions><Button onClick={() => setOpeningProject(false)} disabled={projectBusy}>Cancel</Button><Button variant="contained" onClick={() => void openProject()} disabled={projectBusy || !projectPath.trim()}>Open project</Button></DialogActions>
      </Dialog>
    </Box>
  );

  function renderProjectContext() {
    return <Stack data-tour="project" className="project-context" direction={{ xs: "column", md: "row" }} spacing={2} sx={{ mr: 2, alignItems: "center" }}>
      {projects.length > 0 && <HelpSelectField topic="project" label="Project" size="small" value={selectedProject?.id ?? ""} onChange={(event) => void navigateSafely({ project: event.target.value, view: location.view === "home" ? "workflows" : location.view, workflow: null, run: null, interaction: null, job: null })}>
          {projects.map((project) => <MenuItem key={project.id} value={project.id}>{project.display_name}</MenuItem>)}
        </HelpSelectField>}
      <Button onClick={() => setOpeningProject(true)}>{projects.length ? "Open another project" : "Open a project"}</Button>
    </Stack>;
  }
}
