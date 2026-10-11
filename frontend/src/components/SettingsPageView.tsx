import { NotificationsSettings } from "./NotificationsSettings";
import { ServerAccountSettings } from "./ServerAccountSettings";

import {
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  ListItem,
} from "@mui/material";
import { HelpLabel } from "./HelpTip";
import {
  Alert,
  Box,
  Button,
  List,
  ListItemButton,
  ListItemText,
  Paper,
  Stack,
  Typography,
} from "@mui/material";

import { PathDisplay } from "./PathDisplay";
import { StorageSettings } from "./StorageSettings";
import { DefaultSettingsForm } from "./DefaultSettingsForm";

import { sections } from "./SettingsPageShared";
import type { SettingsPageState } from "./useSettingsPage";
export function SettingsPageView({ state }: { state: SettingsPageState }) {
  const {
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
    draft,
    agents,
    setDraft,
    requestProject,
    tourSection,
    effective,
    setEffective,
    overrides,
    updateOverrides,
    response,
    fieldErrors,
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
  } = state;
  return (
    <Box className="actions-layout settings-layout">
      <Box
        component="nav"
        aria-label="Settings sections"
        data-tour="settings-navigation"
        className="actions-sidebar"
      >
        <Typography variant="h6" sx={{ p: 2 }}>
          Settings
        </Typography>
        <List>
          {sections.map((name) => (
            <ListItem key={name} disablePadding>
              <ListItemButton
                aria-current={name === section ? "page" : undefined}
                selected={name === section}
                onClick={() => {
                  if (name === section) return;
                  if (dirty) setPendingSection(name);
                  else {
                    setSection(name);
                    setNotice(null);
                    setError(null);
                  }
                }}
              >
                <ListItemText primary={name} />
              </ListItemButton>
            </ListItem>
          ))}
        </List>
      </Box>
      <Paper
        component="section"
        aria-label={section}
        variant="outlined"
        className="settings-content"
        data-tour={section === "Storage" ? "storage" : undefined}
      >
        <Stack spacing={3}>
          <Box>
            <Typography
              ref={heading}
              tabIndex={-1}
              component="h1"
              variant="h5"
              className="section-heading"
            >
              {section}
            </Typography>
            <Typography color="text.secondary" sx={{ mt: 1 }}>
              {projectView
                ? `Overrides for ${project?.display_name ?? "the selected project"}. Turn an override off to inherit the saved global value.`
                : section === "Global defaults"
                  ? "Defaults for this Relay installation, across all projects. Saved runs keep their captured choices."
                  : section === "Server and account"
                    ? "Local access and server settings. Changes apply after restarting Relay."
                    : section === "Notifications"
                      ? "Notification preferences for this browser."
                      : section === "Storage"
                        ? "Installation folders and retained project data."
                        : "Learn Relay at your own pace. These preferences belong to this browser."}
            </Typography>
          </Box>
          {error && (
            <Alert
              severity="error"
              action={
                <Button
                  disabled={busy}
                  onClick={() => setRevision((value) => value + 1)}
                >
                  Reload settings
                </Button>
              }
            >
              {error}
            </Alert>
          )}
          {notice && <Alert severity="success">{notice}</Alert>}
          {section === "Global defaults" && (
            <>
              <Typography variant="body2" color="text.secondary">
                Saved job and workflow choices take precedence over these
                defaults.
              </Typography>
              <DefaultSettingsForm
                settings={draft}
                agents={agents?.agents ?? []}
                onChange={(values) => {
                  setDraft(values);
                  setNotice(null);
                }}
                project={requestProject}
                disabled={busy}
                tourActive={Boolean(tourSection)}
              />
            </>
          )}
          {section === "Global defaults" && !agents && (
            <Alert severity="info">
              Open a project with available agent discovery to choose models and
              thinking effort. Other global settings remain editable.
            </Alert>
          )}
          {projectView &&
            (project && effective ? (
              <DefaultSettingsForm
                settings={effective}
                agents={agents?.agents ?? []}
                onChange={setEffective}
                project={requestProject}
                disabled={busy}
                overrides={overrides}
                onOverrides={updateOverrides}
              />
            ) : (
              <Alert severity="info">
                {project
                  ? "Project defaults could not be loaded. Reload settings to try again."
                  : "Open a project to set its overrides."}
              </Alert>
            ))}
          {section === "Server and account" && (
            <ServerAccountSettings state={state} />
          )}
          {section === "Notifications" && (
            <NotificationsSettings state={state} />
          )}
          {section === "Storage" && (
            <Stack spacing={3}>
              <Box component="section" aria-label="Installation folders">
                <Typography variant="h6" sx={{ mb: 1 }}>
                  Installation folders
                </Typography>
                <Box component="dl" className="data-rows">
                  {Object.entries(response.paths).map(([name, path]) => {
                    const label =
                      name === "prompts"
                        ? "Shared instructions"
                        : name.charAt(0).toUpperCase() + name.slice(1);
                    return (
                      <Box key={name} className="data-row">
                        <Typography component="dt">{label}</Typography>
                        <Box component="dd">
                          <PathDisplay path={path} label={label} />
                        </Box>
                      </Box>
                    );
                  })}
                </Box>
              </Box>
              <Typography variant="body2" color="text.secondary">
                Workflow files stay in each project's .relay folder. These
                folders hold installation settings, shared instructions, run
                history, working copies, and process logs.
              </Typography>
              {project && (
                <StorageSettings
                  project={project}
                  requestProject={requestProject}
                />
              )}
            </Stack>
          )}
          {section === "Welcome and guided tour" && (
            <Stack spacing={2} data-tour="onboarding">
              <Typography>
                Welcome slides introduce projects, workflows, live logs, and
                defaults. The spotlight tour explains controls without changing
                your settings or running jobs.
              </Typography>
              <HelpLabel topic="onboarding">
                Replay or reset onboarding
              </HelpLabel>
              <Stack
                direction="row"
                spacing={1}
                useFlexGap
                sx={{ flexWrap: "wrap" }}
              >
                <Button variant="outlined" onClick={onShowWelcome}>
                  Replay welcome slides
                </Button>
                <Button variant="outlined" onClick={onShowTour}>
                  Replay guided tour
                </Button>
                <Button
                  onClick={() =>
                    setOnboardingNotice(
                      onResetOnboarding()
                        ? "Onboarding reset. The welcome slides and tour will appear the next time you open or reload Relay in this browser."
                        : "This browser cannot save onboarding preferences. You can still replay the slides or tour here.",
                    )
                  }
                >
                  Reset onboarding
                </Button>
              </Stack>
              {onboardingNotice && (
                <Alert severity="info">{onboardingNotice}</Alert>
              )}
            </Stack>
          )}
          {editable && (
            <Stack direction="row" spacing={1} className="settings-save">
              <Button
                variant="contained"
                disabled={
                  busy ||
                  !dirty ||
                  Object.keys(fieldErrors).length > 0 ||
                  (projectView && !projectResponse)
                }
                onClick={() => void save(projectView)}
              >
                {busy
                  ? "Saving…"
                  : projectView
                    ? "Save project defaults"
                    : "Save global settings"}
              </Button>
              <Button disabled={busy || !dirty} onClick={discard}>
                Discard changes
              </Button>
            </Stack>
          )}
        </Stack>
      </Paper>
      <Dialog
        open={pendingSection !== null}
        onClose={() => setPendingSection(null)}
        aria-labelledby="settings-discard-title"
      >
        <DialogTitle id="settings-discard-title">Unsaved settings</DialogTitle>
        <DialogContent>
          Discard your changes to open {pendingSection}, or keep editing.
        </DialogContent>
        <DialogActions>
          <Button onClick={() => setPendingSection(null)}>Keep editing</Button>
          <Button
            color="error"
            onClick={() => {
              discard();
              if (pendingSection) setSection(pendingSection);
              setPendingSection(null);
            }}
          >
            Discard changes
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
