import {
  AppBar,
  Alert,
  Box,
  Button,
  CircularProgress,
  Container,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControl,
  InputLabel,
  MenuItem,
  Menu,
  Select,
  Stack,
  Tab,
  Tabs,
  TextField,
  Toolbar,
  Typography,
} from "@mui/material";
import { lazy, Suspense, useCallback, useEffect, useRef, useState } from "react";

import { api, errorMessage } from "./api";
import { AuthView } from "./components/AuthView";
import { GetStarted } from "./components/GetStarted";
import { readLocation, saveLocation, type LocationState } from "./navigation";
import type { AuthState, ProjectRecord } from "./types";

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

export function App() {
  const [auth, setAuth] = useState<AuthState | null>(null);
  const [location, setLocation] = useState(readLocation);
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
  const [setupRunSucceeded, setSetupRunSucceeded] = useState(false);
  const [workflowRevision, setWorkflowRevision] = useState(0);
  const runSucceeded = useCallback(() => setSetupRunSucceeded(true), []);
  const beforeLeave = useRef<(() => Promise<void>) | null>(null);
  const registerNavigation = useCallback((callback: (() => Promise<void>) | null) => { beforeLeave.current = callback; }, []);

  const navigate = useCallback((patch: Partial<LocationState>) => {
    setLocation((current) => ({ ...current, ...patch }));
  }, []);
  const workflowLoaded = useCallback((workflow: string) => navigate({ workflow }), [navigate]);
  const navigateSafely = useCallback(async (patch: Partial<LocationState>) => {
    try { await beforeLeave.current?.(); navigate(patch); }
    catch (caught) { setProjectError(errorMessage(caught)); }
  }, [navigate]);
  const selectRun = useCallback((run: string | null) => {
    setLocation((current) => ({ ...current, run, interaction: run === current.run ? current.interaction : null }));
  }, []);

  useEffect(() => saveLocation(location, true), [location]);

  useEffect(() => {
    const restore = () => setLocation(readLocation());
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
        const next = { ...current, project: linkedRun?.run.project.id ?? current.project ?? context?.project.id ?? inventory.projects[0]?.id ?? null };
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
      navigate({ project: response.project.id, workflow: null, run: null, interaction: null, view: "author" });
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
          <Typography variant="h5" color="primary" sx={{ mr: 3 }}>Relay</Typography>
          <Tabs
            value={location.view}
            onChange={(_event, value: LocationState["view"]) => void navigateSafely({ view: value })}
            sx={{ flex: 1 }}
          >
            <Tab value="author" label="Workflows" />
            <Tab value="runs" label="Runs" />
          </Tabs>
          <Typography variant="body2" color="text.secondary" sx={{ mr: 2 }}>
            {loginRequired ? auth.username : "Login disabled"}
          </Typography>
          {loginRequired && (
            <Button color="inherit" onClick={() => void logout()} disabled={signingOut}>Sign out</Button>
          )}
          <Button aria-haspopup="menu" aria-expanded={helpAnchor !== null} onClick={(event) => setHelpAnchor(event.currentTarget)}>Help</Button>
          <Menu anchorEl={helpAnchor} open={helpAnchor !== null} onClose={() => setHelpAnchor(null)}>
            <MenuItem onClick={() => { setSetupForced(true); setHelpAnchor(null); }}>Get started</MenuItem>
          </Menu>
        </Toolbar>
      </AppBar>
      <Container maxWidth={false} className="app-content">
        {renderProjectContext()}
        {projectReady && selectedProject && <GetStarted key={selectedProject.id} project={selectedProject} requestProject={requestProject}
          forced={setupForced} runSucceeded={setupRunSucceeded} onClose={() => setSetupForced(false)} onOpenProject={() => setOpeningProject(true)}
          onWorkflowCreated={async (key) => {
            await beforeLeave.current?.();
            navigate({ workflow: key, view: "author", run: null, interaction: null });
            setWorkflowRevision((value) => value + 1);
          }} onRunLaunched={(id) => navigate({ run: id, interaction: null, view: "runs" })} />}
        {logoutError && (
          <Alert severity="error" sx={{ mb: 2 }} action={
            <Button color="inherit" onClick={() => void logout()} disabled={signingOut}>Retry</Button>
          }>{logoutError}</Alert>
        )}
        <Suspense fallback={<Box className="loading-panel"><CircularProgress /></Box>}>
          {!projectReady ? <Box className="loading-panel"><CircularProgress aria-label="Loading projects" /></Box>
          : !selectedProject ? <Alert severity="info">Choose a project above, or open a Git repository to begin.</Alert>
          : location.view === "author" ? (
            <WorkflowWorkspace
              key={`${selectedProject.id}-${workflowRevision}`}
              project={selectedProject}
              requestProject={requestProject}
              initialWorkflow={location.workflow}
              onWorkflowLoaded={workflowLoaded}
              onNavigationReady={registerNavigation}
              onRunLaunched={(runId) => {
                navigate({ run: runId, interaction: null, view: "runs" });
              }}
            />
          ) : (
            <RunWorkspace
              selectedRun={location.run}
              project={selectedProject}
              selectedInteraction={location.interaction}
              onRunSucceeded={runSucceeded}
              onSelectRun={selectRun}
            />
          )}
        </Suspense>
      </Container>
      <Dialog open={openingProject} onClose={() => !projectBusy && setOpeningProject(false)} fullWidth>
        <DialogTitle>Open a project</DialogTitle>
        <DialogContent>
          <Typography sx={{ mb: 2 }}>Choose a Git repository on this computer. Relay adds a blank workflow folder if one is missing. Your code and Git branch stay in place.</Typography>
          <TextField fullWidth label="Repository folder" value={projectPath} onChange={(event) => setProjectPath(event.target.value)} placeholder="/path/to/project" />
          {projectError && <Alert severity="error" sx={{ mt: 2 }}>{projectError}</Alert>}
        </DialogContent>
        <DialogActions><Button onClick={() => setOpeningProject(false)} disabled={projectBusy}>Cancel</Button><Button variant="contained" onClick={() => void openProject()} disabled={projectBusy || !projectPath.trim()}>Open project</Button></DialogActions>
      </Dialog>
    </Box>
  );

  function renderProjectContext() {
    return <Stack className="project-context" direction={{ xs: "column", md: "row" }} spacing={2} sx={{ mb: 3, alignItems: { md: "center" } }}>
      <FormControl size="small" sx={{ minWidth: 200 }}>
        <InputLabel id="current-project">Project</InputLabel>
        <Select labelId="current-project" label="Project" value={selectedProject?.id ?? ""} onChange={(event) => void navigateSafely({ project: event.target.value, workflow: null, run: null, interaction: null })}>
          {projects.map((project) => <MenuItem key={project.id} value={project.id}>{project.display_name}</MenuItem>)}
        </Select>
      </FormControl>
      <Box sx={{ flex: 1 }}>
        <Typography variant="body2" color="text.secondary">{selectedProject?.canonical_path ?? "No project selected"}</Typography>
        <Typography variant="body2">{location.view === "author" ? "Workflows: choose the steps, save your instructions, and start work." : "Runs: follow progress, review results, and respond when your input is needed."}</Typography>
      </Box>
      <Button onClick={() => setOpeningProject(true)}>Open another project</Button>
      {projectError && !openingProject && <Alert severity="error">{projectError}</Alert>}
    </Stack>;
  }
}
