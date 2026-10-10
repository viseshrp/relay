import { ViewSkeleton } from "./components/ViewSkeleton";
import { Alert, Box, Button, Container, Stack } from "@mui/material";
import { Suspense } from "react";
import { WorkspaceBoundary } from "./components/WorkspaceBoundary";

import { resetOnboarding } from "./onboarding";

import { GettingStartedHome } from "./components/GettingStartedHome";
import { HomeDashboard } from "./components/HomeDashboard";

import { GetStarted } from "./components/GetStarted";

import { SettingsPage, WorkflowWorkspace, RunWorkspace } from "./AppShared";
import type { AppState } from "./useApp";
export function AppMain({ state }: { state: AppState }) {
  const {
    updatedFrontend,
    reloading,
    reloadSafely,
    attention,
    projectError,
    openingProject,
    setupDismissed,
    setupRunSucceeded,
    setupReady,
    openSetup,
    projectReady,
    selectedProject,
    dismissSetup,
    setupForced,
    requestProject,
    runSucceeded,
    setSetupForced,
    setOpeningProject,
    beforeLeave,
    navigate,
    setWorkflowRevision,
    logoutError,
    logout,
    signingOut,
    location,
    showWelcome,
    setProjects,
    navigateSafely,
    tourSection,
    showTour,
    registerNavigation,
    projects,
    workflowRevision,
    workflowCreate,
    launchWorkflow,
    setLaunchWorkflow,
    workflowLoaded,
    selectRun,
    setWorkflowCreate,
  } = state;
  return (
    <Container
      component="main"
      aria-label={location.view === "home" ? "Relay home" : undefined}
      id="main-content"
      tabIndex={-1}
      maxWidth={false}
      className="app-content"
    >
      {updatedFrontend && (
        <Alert
          severity="info"
          sx={{ mb: 2 }}
          action={
            <Button disabled={reloading} onClick={() => void reloadSafely()}>
              Reload Relay
            </Button>
          }
        >
          Relay was updated. Reload to use the current version.
        </Alert>
      )}
      {attention.error && (
        <Alert severity="warning" sx={{ mb: 2 }}>
          {attention.error}
        </Alert>
      )}
      {projectError && !openingProject && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {projectError}
        </Alert>
      )}
      {projectReady && setupReady && !setupDismissed && !setupRunSucceeded && (
        <Alert
          className="setup-banner"
          severity="info"
          role="region"
          aria-label="Welcome to Relay"
          sx={{ mb: 2 }}
          action={
            <Stack
              direction="row"
              spacing={1}
              useFlexGap
              sx={{ flexWrap: "wrap" }}
            >
              <Button
                onClick={openSetup}
                disabled={!projectReady || !selectedProject}
              >
                Get started
              </Button>
              <Button onClick={dismissSetup}>Dismiss welcome</Button>
            </Stack>
          }
        >
          New to Relay? Check agents and choose your first workflow.
        </Alert>
      )}
      {setupForced && projectReady && selectedProject && (
        <GetStarted
          key={selectedProject.id}
          project={selectedProject}
          requestProject={requestProject}
          runSucceeded={setupRunSucceeded}
          onClose={() => setSetupForced(false)}
          onOpenProject={() => {
            setSetupForced(false);
            setOpeningProject(true);
          }}
          onWorkflowCreated={async (key) => {
            await beforeLeave.current?.();
            navigate({
              workflow: key,
              view: "workflows",
              run: null,
              interaction: null,
              job: null,
            });
            setWorkflowRevision((value) => value + 1);
          }}
          onRunLaunched={(id) => {
            setSetupForced(false);
            navigate({ run: id, interaction: null, job: null, view: "runs" });
          }}
        />
      )}
      {logoutError && (
        <Alert
          severity="error"
          sx={{ mb: 2 }}
          action={
            <Button
              color="inherit"
              onClick={() => void logout()}
              disabled={signingOut}
            >
              Retry
            </Button>
          }
        >
          {logoutError}
        </Alert>
      )}
      <WorkspaceBoundary>
        <Suspense
          fallback={
            <ViewSkeleton view={location.run ? "summary" : location.view} />
          }
        >
          {!projectReady || !setupReady ? (
            <ViewSkeleton view={location.run ? "summary" : location.view} />
          ) : location.view === "home" ? (
            <HomeDashboard
              onOpenProject={() => setOpeningProject(true)}
              onShowWelcome={() => void showWelcome()}
              onNavigate={(project, view, run) => {
                setProjects((current) => [
                  ...current.filter((value) => value.id !== project.id),
                  project,
                ]);
                void navigateSafely({
                  project: project.id,
                  view,
                  workflow: null,
                  run: run?.id ?? null,
                  job: null,
                  interaction: run?.request?.id ?? null,
                });
              }}
            />
          ) : location.view === "settings" ? (
            <SettingsPage
              tourSection={tourSection}
              onShowWelcome={() => void showWelcome()}
              onShowTour={() => void showTour()}
              onResetOnboarding={resetOnboarding}
              project={selectedProject}
              requestProject={requestProject}
              notifications={attention.notifications}
              onToggleNotifications={attention.toggleNotifications}
              onNavigationReady={registerNavigation}
            />
          ) : projects.length === 0 && !projectError ? (
            <GettingStartedHome
              onOpenProject={() => setOpeningProject(true)}
              onShowWelcome={() => void showWelcome()}
            />
          ) : !selectedProject ? (
            <Alert severity="info">
              Choose a project above, or open a Git repository to begin.
            </Alert>
          ) : location.view === "workflows" ? (
            <WorkflowWorkspace
              key={`${selectedProject.id}-${workflowRevision}`}
              project={selectedProject}
              requestProject={requestProject}
              initialCreate={workflowCreate}
              initialWorkflow={location.workflow}
              initialLaunch={
                launchWorkflow === location.workflow && launchWorkflow !== null
              }
              onLaunchClosed={() => setLaunchWorkflow(null)}
              onWorkflowLoaded={workflowLoaded}
              onNavigationReady={registerNavigation}
              onRunLaunched={(runId) => {
                setLaunchWorkflow(null);
                navigate({
                  run: runId,
                  interaction: null,
                  job: null,
                  view: "runs",
                });
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
              onEditWorkflow={(workflow) => {
                setWorkflowCreate(!workflow);
                setWorkflowRevision((value) => value + 1);
                navigate({
                  workflow: workflow || null,
                  view: "workflows",
                  run: null,
                  interaction: null,
                  job: null,
                });
              }}
              onRunWorkflow={(workflow) => {
                setLaunchWorkflow(workflow);
                navigate({
                  workflow,
                  view: "workflows",
                  run: null,
                  interaction: null,
                  job: null,
                });
              }}
            />
          )}
        </Suspense>
      </WorkspaceBoundary>
    </Container>
  );
}
