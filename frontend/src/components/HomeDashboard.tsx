import { Alert, Box, Button, Chip, CircularProgress, Paper, Stack, TextField, Typography } from "@mui/material";
import { useEffect, useRef, useState } from "react";
import { errorMessage, readDashboard } from "../api";
import { jobDuration } from "../job";
import { stageLabel, statusLabel } from "../navigation";
import type { DashboardData, DashboardPage, DashboardRun, DashboardSection, ProjectRecord } from "../types";
import { useClock } from "../useClock";
import { PathDisplay } from "./PathDisplay";
import { ActionIcon, StatusIcon } from "./ActionIcon";
import { GettingStartedHome } from "./GettingStartedHome";

function mergePage<T extends { id: string }>(before: DashboardPage<T>, after: DashboardPage<T>): DashboardPage<T> {
  const items = new Map(before.items.map((item) => [item.id, item]));
  after.items.forEach((item) => items.set(item.id, item));
  return { items: [...items.values()], next_cursor: after.next_cursor };
}

export function HomeDashboard({ onOpenProject, onShowWelcome, onNavigate }: {
  onOpenProject: () => void; onShowWelcome: () => void;
  onNavigate: (project: ProjectRecord, view: "workflows" | "runs", run?: DashboardRun) => void;
}) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [updated, setUpdated] = useState<string | null>(null);
  const refresh = useRef<() => void>(() => undefined);
  const more = useRef<(section: DashboardSection) => void>(() => undefined);
  const current = useRef(data); current.current = data;
  const now = useClock(Boolean(data?.counts.unfinished));

  useEffect(() => {
    const controller = new AbortController();
    let inFlight = false;
    const sizes: Record<DashboardSection, number> = { projects: 10, waiting: 10, active: 10, recent: 10 };
    async function update(): Promise<void> {
      if (inFlight || controller.signal.aborted) return;
      inFlight = true; setBusy(true);
      try {
        const value = await readDashboard(controller.signal, query);
        if (!value.projects || !value.waiting || !value.active || !value.recent) throw new Error("Relay returned an incomplete dashboard.");
        const next: DashboardData = { counts: value.counts, projects: value.projects, waiting: value.waiting, active: value.active, recent: value.recent };
        // Refresh every visible page so finished runs do not linger in the active list.
        for (const section of ["projects", "waiting", "active", "recent"] as const) {
          let page = next[section];
          while (page.items.length < sizes[section] && page.next_cursor) {
            const response = await readDashboard(controller.signal, query, section, page.next_cursor);
            if (section === "projects" && response.projects) next.projects = mergePage(next.projects, response.projects);
            if (section === "waiting" && response.waiting) next.waiting = mergePage(next.waiting, response.waiting);
            if (section === "active" && response.active) next.active = mergePage(next.active, response.active);
            if (section === "recent" && response.recent) next.recent = mergePage(next.recent, response.recent);
            if (next[section].next_cursor === page.next_cursor) break;
            page = next[section];
          }
        }
        if (!controller.signal.aborted) { setData(next); setError(null); setUpdated(new Date().toISOString()); }
      } catch (caught) { if (!controller.signal.aborted) setError(errorMessage(caught)); }
      finally { inFlight = false; if (!controller.signal.aborted) setBusy(false); }
    }
    async function loadMore(section: DashboardSection): Promise<void> {
      const before = current.current;
      const cursor = before?.[section].next_cursor;
      if (!before || !cursor || inFlight || controller.signal.aborted) return;
      inFlight = true; setBusy(true);
      try {
        const value = await readDashboard(controller.signal, query, section, cursor);
        const next = { ...before, counts: value.counts };
        if (section === "projects" && value.projects) next.projects = mergePage(before.projects, value.projects);
        if (section === "waiting" && value.waiting) next.waiting = mergePage(before.waiting, value.waiting);
        if (section === "active" && value.active) next.active = mergePage(before.active, value.active);
        if (section === "recent" && value.recent) next.recent = mergePage(before.recent, value.recent);
        sizes[section] = next[section].items.length;
        if (!controller.signal.aborted) { setData(next); setError(null); }
      } catch (caught) { if (!controller.signal.aborted) setError(errorMessage(caught)); }
      finally { inFlight = false; if (!controller.signal.aborted) setBusy(false); }
    }
    const focused = () => { if (document.visibilityState === "visible") void update(); };
    refresh.current = () => void update(); more.current = (section) => void loadMore(section);
    void update();
    const timer = window.setInterval(focused, 5000);
    window.addEventListener("focus", focused); document.addEventListener("visibilitychange", focused);
    return () => { controller.abort(); window.clearInterval(timer); window.removeEventListener("focus", focused); document.removeEventListener("visibilitychange", focused); };
  }, [query]);

  function runList(section: "waiting" | "active" | "recent", title: string, empty: string) {
    const page = data?.[section];
    return <Paper component="section" aria-label={title} variant="outlined" className={`dashboard-section dashboard-${section}`}>
      <div className="dashboard-section-heading"><Typography component="h2" variant="h6">{title}</Typography><span className="dashboard-section-count">{section === "waiting" ? data?.counts.waiting : section === "active" ? Math.max(0, (data?.counts.unfinished ?? 0) - (data?.counts.waiting ?? 0)) : "Latest results"}</span></div>
      {!page?.items.length && <Typography className="dashboard-empty" color="text.secondary">{empty}</Typography>}
      <div className="dashboard-run-list">{page?.items.map((run) => <div className="dashboard-run" key={run.id}>
        <StatusIcon status={run.request ? "waiting" : run.status} size={22} />
        <div className="dashboard-run-body"><Button className="dashboard-run-link" onClick={() => onNavigate(run.project, "runs", run)}>{run.title || stageLabel(run.workflow_key.replace(/\.ya?ml$/, ""))} <span className="dashboard-run-number">#{run.number}</span></Button>
          <Typography variant="body2" color="text.secondary">{run.project.display_name} · {run.request ? `${stageLabel(run.request.kind)} · ${stageLabel(run.request.scope_path)}` : `${statusLabel(run.status)}${run.dispatch_paused ? " · Paused" : ""}`}</Typography>
          {section === "recent" && <Typography variant="caption" color="text.secondary">{run.source_branch ?? "Detached HEAD"} · {new Date(run.ended_at ?? run.created_at).toLocaleString()}</Typography>}
        </div>
        <Typography variant="body2" className="dashboard-duration" color="text.secondary"><ActionIcon name="clock" size={14} /> {jobDuration(run.started_at, run.ended_at, now)}</Typography>
        {run.request && <Button variant="outlined" size="small" onClick={() => onNavigate(run.project, "runs", run)}>Open request</Button>}
      </div>)}</div>
      {page?.next_cursor && <Button disabled={busy} fullWidth onClick={() => more.current(section)}>Show more {title.toLowerCase()}</Button>}
    </Paper>;
  }

  return <Box className="dashboard" component="main" aria-label="Relay home">
    <div className="dashboard-heading"><Box><Typography component="h1" variant="h4">Your work at a glance</Typography><Typography color="text.secondary">Projects, runs, and requests that need your attention.</Typography></Box>
      <Stack direction="row" spacing={1}><Button variant="outlined" startIcon={<ActionIcon name="refresh" />} disabled={busy} onClick={() => refresh.current()}>Refresh</Button><Button variant="contained" onClick={onOpenProject}>Open project</Button></Stack></div>
    {error && <Alert severity="warning">{data ? "Updates unavailable. Showing the last successful refresh. " : ""}{error}</Alert>}
    {!data ? <div className="loading-panel">{!error && <CircularProgress aria-label="Loading dashboard" />}</div> : data.counts.projects === 0 ? <GettingStartedHome onOpenProject={onOpenProject} onShowWelcome={onShowWelcome} /> : <>
      <div className="dashboard-stats">{[["Projects", data.counts.projects], ["Waiting for you", data.counts.waiting], ["Unfinished runs", data.counts.unfinished], ["Paused runs", data.counts.paused]].map(([label, value]) => <Paper variant="outlined" className="dashboard-stat" key={label}><Typography variant="body2" color="text.secondary">{label}</Typography><Typography variant="h4">{value}</Typography></Paper>)}</div>
      {runList("waiting", "Waiting for you", "No requests need your response.")}
      <div className="dashboard-work-grid">{runList("active", "Active and paused runs", "No jobs are running or paused.")}{runList("recent", "Recent results", "Completed runs will appear here.")}</div>
      <section aria-label="Projects"><div className="dashboard-section-heading"><Typography component="h2" variant="h5">Your projects</Typography><TextField size="small" label="Find a project" value={query} onChange={(event) => setQuery(event.target.value)} slotProps={{ htmlInput: { maxLength: 1024 } }} /></div>
        <div className="dashboard-project-grid">{data.projects.items.map((project) => <Paper variant="outlined" component="article" aria-label={project.display_name} key={project.id} className="dashboard-project">
          <Typography component="h3" variant="h6">{project.display_name}</Typography><PathDisplay path={project.canonical_path} label={project.display_name} />
          <Stack direction="row" spacing={1} useFlexGap sx={{ flexWrap: "wrap", my: 2 }}>{project.unfinished_count > 0 && <Chip size="small" label={`${project.unfinished_count} unfinished`} />}{project.waiting_count > 0 && <Chip size="small" color="warning" label={`${project.waiting_count} waiting`} />}</Stack>
          {project.latest_run ? <div className="dashboard-project-result"><StatusIcon status={project.latest_run.status} /><Typography variant="body2">{project.latest_run.title || stageLabel(project.latest_run.workflow_key)} #{project.latest_run.number}<br /><span className="dashboard-muted">{statusLabel(project.latest_run.status)} · {new Date(project.latest_run.created_at).toLocaleDateString()}</span></Typography></div> : <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>No runs yet</Typography>}
          <Stack direction="row" spacing={1}><Button variant="outlined" onClick={() => onNavigate(project, "workflows")}>Workflows</Button><Button onClick={() => onNavigate(project, "runs")}>Runs</Button></Stack>
        </Paper>)}</div>
        {!data.projects.items.length && <Typography className="dashboard-empty" color="text.secondary">No projects match your search.</Typography>}
        {data.projects.next_cursor && <Button disabled={busy} onClick={() => more.current("projects")}>Show more projects</Button>}
      </section>
      {updated && <Typography variant="caption" color="text.secondary" className="dashboard-updated">Updated {new Date(updated).toLocaleTimeString()} · Refreshes while this page is visible</Typography>}
    </>}
  </Box>;
}
