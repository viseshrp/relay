import { ViewSkeleton } from "./ViewSkeleton";
import {
  Alert,
  Box,
  Button,
  Chip,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";

import { stageLabel, statusLabel } from "../navigation";

import { PathDisplay } from "./PathDisplay";
import { ActionIcon, StatusIcon } from "./ActionIcon";
import { GettingStartedHome } from "./GettingStartedHome";

import type { HomeDashboardState } from "./useHomeDashboard";
import { viewHref } from "../navigation";
export function HomeDashboardView({ state }: { state: HomeDashboardState }) {
  const {
    busy,
    refresh,
    onOpenProject,
    error,
    data,
    onShowWelcome,
    runList,
    query,
    setQuery,
    onNavigate,
    more,
    updated,
  } = state;
  return (
    <Box className="dashboard" component="div" aria-label="Relay home">
      <div className="dashboard-heading">
        <Box>
          <Typography component="h1" variant="h5">
            Your work at a glance
          </Typography>
          <Typography color="text.secondary">
            Projects, runs, and requests that need your attention.
          </Typography>
        </Box>
        <Stack direction="row" spacing={1}>
          <Button
            variant="outlined"
            startIcon={<ActionIcon name="refresh" />}
            disabled={busy}
            onClick={() => refresh.current()}
          >
            Refresh
          </Button>
          <Button variant="contained" onClick={onOpenProject}>
            Open project
          </Button>
        </Stack>
      </div>
      {error && (
        <Alert severity="warning">
          {data
            ? "Updates unavailable. Showing the last successful refresh. "
            : ""}
          {error}
        </Alert>
      )}
      {!data ? (
        <div>{!error && <ViewSkeleton view="home" header={false} />}</div>
      ) : data.counts.projects === 0 ? (
        <GettingStartedHome
          heading="h2"
          onOpenProject={onOpenProject}
          onShowWelcome={onShowWelcome}
        />
      ) : (
        <>
          <div className="dashboard-stats">
            {[
              ["Projects", data.counts.projects],
              ["Waiting for you", data.counts.waiting],
              ["Unfinished runs", data.counts.unfinished],
              ["Paused runs", data.counts.paused],
            ].map(([label, value]) => (
              <Paper variant="outlined" className="dashboard-stat" key={label}>
                <Typography variant="body2" color="text.secondary">
                  {label}
                </Typography>
                <Typography component="p" variant="h5">
                  {value}
                </Typography>
              </Paper>
            ))}
          </div>
          {data.waiting.items.length ? (
            runList(
              "waiting",
              "Waiting for you",
              "No requests need your response.",
            )
          ) : (
            <Typography
              component="section"
              aria-label="Waiting for you"
              className="dashboard-waiting-empty"
              color="text.secondary"
            >
              No requests need your response.
            </Typography>
          )}
          <div className="dashboard-work-grid">
            {runList(
              "active",
              "Active and paused runs",
              "No active jobs. Runs waiting for your response appear above.",
            )}
            {runList(
              "recent",
              "Recent results",
              "Completed runs will appear here.",
            )}
          </div>
          <section aria-label="Projects">
            <div className="dashboard-section-heading">
              <Typography component="h2" variant="h5">
                Your projects
              </Typography>
              <TextField
                size="small"
                label="Find a project"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                slotProps={{ htmlInput: { maxLength: 1024 } }}
              />
            </div>
            <div className="dashboard-project-grid">
              {data.projects.items.map((project) => (
                <Paper
                  variant="outlined"
                  component="article"
                  aria-label={project.display_name}
                  key={project.id}
                  className="dashboard-project"
                >
                  <Typography component="h3" variant="h6">
                    {project.display_name}
                  </Typography>
                  <PathDisplay
                    path={project.canonical_path}
                    label={project.display_name}
                  />
                  <Stack
                    direction="row"
                    spacing={1}
                    useFlexGap
                    sx={{ flexWrap: "wrap", my: 2 }}
                  >
                    {project.unfinished_count > 0 && (
                      <Chip
                        size="small"
                        label={`${project.unfinished_count} unfinished`}
                      />
                    )}
                    {project.waiting_count > 0 && (
                      <Chip
                        size="small"
                        color="warning"
                        label={`${project.waiting_count} waiting`}
                      />
                    )}
                  </Stack>
                  {project.latest_run ? (
                    <div className="dashboard-project-result">
                      <StatusIcon status={project.latest_run.status} />
                      <Typography variant="body2">
                        {project.latest_run.title ||
                          stageLabel(project.latest_run.workflow_key)}{" "}
                        #{project.latest_run.number}
                        <br />
                        <span className="dashboard-muted">
                          {statusLabel(project.latest_run.status)} ·{" "}
                          {new Date(
                            project.latest_run.created_at,
                          ).toLocaleDateString()}
                        </span>
                      </Typography>
                    </div>
                  ) : (
                    <Typography
                      variant="body2"
                      color="text.secondary"
                      sx={{ mb: 2 }}
                    >
                      No runs yet
                    </Typography>
                  )}
                  <Stack direction="row" spacing={1}>
                    <Button
                      component="a"
                      href={viewHref("workflows", project.id)}
                      aria-label={`Open ${project.display_name} workflows`}
                      variant="outlined"
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
                        onNavigate(project, "workflows");
                      }}
                    >
                      Workflows
                    </Button>
                    <Button
                      component="a"
                      href={viewHref("runs", project.id)}
                      aria-label={`Open ${project.display_name} runs`}
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
                        onNavigate(project, "runs");
                      }}
                    >
                      Runs
                    </Button>
                  </Stack>
                </Paper>
              ))}
            </div>
            {!data.projects.items.length && (
              <Typography className="dashboard-empty" color="text.secondary">
                No projects match your search.
              </Typography>
            )}
            {data.projects.next_cursor && (
              <Button disabled={busy} onClick={() => more.current("projects")}>
                Show more projects
              </Button>
            )}
          </section>
          {updated && (
            <Typography
              variant="caption"
              color="text.secondary"
              className="dashboard-updated"
            >
              Updated {new Date(updated).toLocaleTimeString()} · Refreshes while
              this page is visible
            </Typography>
          )}
        </>
      )}
    </Box>
  );
}
