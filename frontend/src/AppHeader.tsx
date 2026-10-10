import {
  AppBar,
  Box,
  Button,
  Divider,
  MenuItem,
  Menu,
  Toolbar,
} from "@mui/material";

import { ActionIcon } from "./components/ActionIcon";

import { type HelpGuide } from "./components/HelpGuides";
import { viewHref } from "./navigation";

import type { AppState } from "./useApp";
export function AppHeader({ state }: { state: AppState }) {
  const {
    header,
    navigateSafely,
    renderProjectContext,
    location,
    attention,
    mobileNav,
    setMobileNav,
    helpButton,
    loginRequired,
    auth,
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
  } = state;
  const href = (view: "home" | "workflows" | "runs" | "settings") =>
    viewHref(view, location.project, {
      ...(location.workflow ? { workflow: location.workflow } : {}),
      ...(location.run ? { run: location.run } : {}),
      ...(location.job ? { job: location.job } : {}),
      ...(location.interaction ? { interaction: location.interaction } : {}),
    });
  return (
    <AppBar
      ref={header}
      position="sticky"
      color="inherit"
      elevation={0}
      className="app-header"
    >
      <Toolbar>
        <Button
          component="a"
          href="/?view=home"
          aria-label="Relay home"
          className="relay-home-link"
          onClick={(event) => {
            if (
              event.button !== 0 ||
              event.metaKey ||
              event.ctrlKey ||
              event.shiftKey ||
              event.altKey
            )
              return;
            event.preventDefault();
            void navigateSafely({
              view: "home",
              workflow: null,
              run: null,
              job: null,
              interaction: null,
            });
          }}
        >
          Relay
        </Button>
        {renderProjectContext()}
        <Box
          component="nav"
          aria-label="Main navigation"
          className="main-navigation"
        >
          {(["workflows", "runs", "settings"] as const).map((view) => (
            <Button
              component="a"
              key={view}
              href={href(view)}
              aria-current={location.view === view ? "page" : undefined}
              data-tour={
                view === "workflows"
                  ? "workflow-tab"
                  : view === "runs"
                    ? "runs-tab"
                    : "settings-tab"
              }
              onClick={(event) => {
                if (
                  event.button !== 0 ||
                  event.metaKey ||
                  event.ctrlKey ||
                  event.shiftKey ||
                  event.altKey
                )
                  return;
                event.preventDefault();
                void navigateSafely({ view });
              }}
            >
              {view === "runs"
                ? `Runs${attention.attention.waiting_count ? ` (${attention.attention.waiting_count})` : ""}`
                : view === "workflows"
                  ? "Workflows"
                  : "Settings"}
            </Button>
          ))}
        </Box>
        <Button
          className="mobile-navigation"
          data-tour="mobile-navigation"
          aria-haspopup="menu"
          aria-expanded={Boolean(mobileNav)}
          onClick={(event) => setMobileNav(event.currentTarget)}
        >
          Navigate
        </Button>
        <Menu
          anchorEl={mobileNav}
          open={Boolean(mobileNav)}
          onClose={() => setMobileNav(null)}
        >
          {(["home", "workflows", "runs", "settings"] as const).map((view) => (
            <MenuItem
              component="a"
              key={view}
              href={href(view)}
              aria-current={view === location.view ? "page" : undefined}
              onClick={(event) => {
                if (event.button !== 0 || event.metaKey || event.ctrlKey)
                  return;
                event.preventDefault();
                setMobileNav(null);
                void navigateSafely({ view });
              }}
            >
              {view === "home"
                ? "Home"
                : view === "workflows"
                  ? "Workflows"
                  : view === "runs"
                    ? "Runs"
                    : "Settings"}
            </MenuItem>
          ))}
        </Menu>
        <Button
          ref={helpButton}
          aria-label={
            loginRequired ? `Account menu for ${auth.username}` : "Help"
          }
          aria-haspopup="menu"
          aria-expanded={helpAnchor !== null}
          endIcon={<ActionIcon name="down" />}
          onClick={(event) => setHelpAnchor(event.currentTarget)}
        >
          {loginRequired ? auth.username : "Help"}
        </Button>
        <Menu
          anchorEl={helpAnchor}
          open={helpAnchor !== null}
          onClose={() => setHelpAnchor(null)}
        >
          {loginRequired && (
            <MenuItem
              onClick={() => {
                setHelpAnchor(null);
                void navigateSafely({
                  view: "settings",
                  run: null,
                  job: null,
                  interaction: null,
                });
              }}
            >
              Settings
            </MenuItem>
          )}
          {(
            [
              "Getting started",
              "Coming from GitHub Actions",
              "Keyboard shortcuts",
            ] as HelpGuide[]
          ).map((name) => (
            <MenuItem
              key={name}
              onClick={() => {
                setHelpAnchor(null);
                setGuide(name);
              }}
            >
              {name}
            </MenuItem>
          ))}
          {loginRequired && <Divider />}
          <MenuItem
            onClick={
              selectedProject
                ? openSetup
                : () => {
                    setHelpAnchor(null);
                    setOpeningProject(true);
                  }
            }
          >
            Get started
          </MenuItem>
          <MenuItem
            onClick={() => {
              setHelpAnchor(null);
              void showWelcome();
            }}
          >
            Welcome slides
          </MenuItem>
          <MenuItem
            onClick={() => {
              setHelpAnchor(null);
              void showTour();
            }}
          >
            Guided tour
          </MenuItem>
          <MenuItem
            onClick={() => {
              void attention.toggleNotifications();
              setHelpAnchor(null);
            }}
          >
            {attention.notifications
              ? "Disable desktop notifications"
              : "Enable desktop notifications"}
          </MenuItem>
          {loginRequired && <Divider />}
          {loginRequired && (
            <MenuItem
              disabled={signingOut}
              onClick={() => {
                setHelpAnchor(null);
                void logout();
              }}
            >
              Sign out
            </MenuItem>
          )}
        </Menu>
      </Toolbar>
    </AppBar>
  );
}
