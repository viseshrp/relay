import { AppHeader } from "./AppHeader";
import { AppMain } from "./AppMain";
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Typography,
} from "@mui/material";

import { HelpTextField } from "./components/HelpTip";
import { WelcomeCarousel } from "./components/WelcomeCarousel";
import { GuidedTour } from "./components/GuidedTour";

import { ProjectFolderValidation } from "./components/ProjectFolderValidation";
import { FolderPicker } from "./components/FolderPicker";

import { HelpGuides } from "./components/HelpGuides";

import type { AppState } from "./useApp";
export function AppView({ state }: { state: AppState }) {
  const {
    helpButton,
    setGuide,
    setOpeningProject,
    showTour,
    projectError,
    openingProject,
    projectReady,
    dismissSetup,
    setupForced,
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
  } = state;
  return (
    <Box sx={{ minHeight: "100vh" }}>
      <a
        className="skip-link"
        href="#main-content"
        onClick={() => document.getElementById("main-content")?.focus()}
      >
        Skip to content
      </a>
      <AppHeader state={state} />
      <AppMain state={state} />
      <HelpGuides guide={guide} onClose={() => setGuide(null)} />
      {projectReady && welcomeOpen && (
        <WelcomeCarousel
          onClose={() => {
            dismissSetup();
            setWelcomeOpen(false);
            helpButton.current?.focus();
          }}
          onShowTour={() => {
            dismissSetup();
            setWelcomeOpen(false);
            void showTour();
          }}
        />
      )}
      {projectReady &&
        !welcomeOpen &&
        !openingProject &&
        !setupForced &&
        tourRequested && (
          <GuidedTour onDestination={tourDestination} onClose={closeTour} />
        )}
      <Dialog
        open={openingProject}
        onClose={() => !projectBusy && setOpeningProject(false)}
        fullWidth
      >
        <DialogTitle>Open a project</DialogTitle>
        <DialogContent>
          <Typography sx={{ mb: 2 }}>
            Choose a Git repository on this computer. Relay adds a blank
            workflow folder if one is missing. Your code and Git branch stay in
            place.
          </Typography>
          <HelpTextField
            topic="project"
            label="Repository folder"
            fullWidth
            value={projectPath}
            onChange={(event) => setProjectPath(event.target.value)}
            placeholder="/path/to/project"
          />
          <Box sx={{ mt: 2 }}>
            <ProjectFolderValidation
              path={projectPath}
              disabled={projectBusy}
              onValidated={setProjectValid}
              onSelect={setProjectPath}
            />
            <FolderPicker disabled={projectBusy} onSelect={setProjectPath} />
          </Box>
          {projectError && (
            <Alert severity="error" sx={{ mt: 2 }}>
              {projectError}
            </Alert>
          )}
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => setOpeningProject(false)}
            disabled={projectBusy}
          >
            Cancel
          </Button>
          <Button
            variant="contained"
            onClick={() => void openProject()}
            disabled={projectBusy || !projectPath.trim() || !projectValid}
          >
            Open project
          </Button>
        </DialogActions>
      </Dialog>
    </Box>
  );
}
