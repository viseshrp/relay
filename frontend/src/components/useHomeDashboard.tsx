import { Button, Paper, Typography } from "@mui/material";
import { useEffect, useRef, useState } from "react";
import { pollVisible } from "../poll-visible";
import { RelayApiError, errorMessage, readDashboard } from "../api";
import { jobDuration } from "../job";
import { stageLabel, statusLabel } from "../navigation";
import type {
  DashboardData,
  DashboardRun,
  DashboardSection,
  ProjectRecord,
} from "../types";
import { useClock } from "../useClock";

import { ActionIcon, StatusIcon } from "./ActionIcon";

import { mergePage } from "./HomeDashboardShared";
export function useHomeDashboard({
  onOpenProject,
  onShowWelcome,
  onNavigate,
}: {
  onOpenProject: () => void;
  onShowWelcome: () => void;
  onNavigate: (
    project: ProjectRecord,
    view: "workflows" | "runs",
    run?: DashboardRun,
  ) => void;
}) {
  const [data, setData] = useState<DashboardData | null>(null);
  const [query, setQuery] = useState("");
  const [expandedRecent, setExpandedRecent] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [updated, setUpdated] = useState<string | null>(null);
  const refresh = useRef<() => void>(() => undefined);
  const more = useRef<(section: DashboardSection) => void>(() => undefined);
  const current = useRef(data);
  current.current = data;
  const now = useClock(Boolean(data?.counts.unfinished));

  useEffect(() => {
    const controller = new AbortController();
    let inFlight = false;
    const sizes: Record<DashboardSection, number> = {
      projects: 10,
      waiting: 10,
      active: 10,
      recent: 10,
    };
    async function update() {
      if (inFlight || controller.signal.aborted) return;
      inFlight = true;
      setBusy(true);
      try {
        const value = await readDashboard(controller.signal, query);
        if (!value.projects || !value.waiting || !value.active || !value.recent)
          throw new Error("Relay returned an incomplete dashboard.");
        const next: DashboardData = {
          counts: value.counts,
          projects: value.projects,
          waiting: value.waiting,
          active: value.active,
          recent: value.recent,
        };
        // Refresh every visible page so finished runs do not linger in the active list.
        for (const section of [
          "projects",
          "waiting",
          "active",
          "recent",
        ] as const) {
          let page = next[section];
          while (page.items.length < sizes[section] && page.next_cursor) {
            const response = await readDashboard(
              controller.signal,
              query,
              section,
              page.next_cursor,
            );
            if (section === "projects" && response.projects)
              next.projects = mergePage(next.projects, response.projects);
            if (section === "waiting" && response.waiting)
              next.waiting = mergePage(next.waiting, response.waiting);
            if (section === "active" && response.active)
              next.active = mergePage(next.active, response.active);
            if (section === "recent" && response.recent)
              next.recent = mergePage(next.recent, response.recent);
            if (next[section].next_cursor === page.next_cursor) break;
            page = next[section];
          }
        }
        if (!controller.signal.aborted) {
          setData(next);
          setError(null);
          setUpdated(new Date().toISOString());
        }
        return next;
      } catch (caught) {
        if (!controller.signal.aborted)
          setError(
            caught instanceof RelayApiError && caught.status === 401
              ? null
              : errorMessage(caught),
          );
        throw caught;
      } finally {
        inFlight = false;
        if (!controller.signal.aborted) setBusy(false);
      }
    }
    async function loadMore(section: DashboardSection): Promise<void> {
      const before = current.current;
      const cursor = before?.[section].next_cursor;
      if (!before || !cursor || inFlight || controller.signal.aborted) return;
      inFlight = true;
      setBusy(true);
      try {
        const value = await readDashboard(
          controller.signal,
          query,
          section,
          cursor,
        );
        const next = { ...before, counts: value.counts };
        if (section === "projects" && value.projects)
          next.projects = mergePage(before.projects, value.projects);
        if (section === "waiting" && value.waiting)
          next.waiting = mergePage(before.waiting, value.waiting);
        if (section === "active" && value.active)
          next.active = mergePage(before.active, value.active);
        if (section === "recent" && value.recent)
          next.recent = mergePage(before.recent, value.recent);
        sizes[section] = next[section].items.length;
        if (!controller.signal.aborted) {
          setData(next);
          setError(null);
        }
      } catch (caught) {
        if (!controller.signal.aborted) setError(errorMessage(caught));
      } finally {
        inFlight = false;
        if (!controller.signal.aborted) setBusy(false);
      }
    }
    const polling = pollVisible(update);
    refresh.current = polling.refresh;
    more.current = (section) => void loadMore(section);
    return () => {
      controller.abort();
      polling.stop();
    };
  }, [query]);

  function runList(
    section: "waiting" | "active" | "recent",
    title: string,
    empty: string,
  ) {
    const page = data?.[section];
    return (
      <Paper
        component="section"
        aria-label={title}
        variant="outlined"
        className={`dashboard-section dashboard-${section}`}
      >
        <div className="dashboard-section-heading">
          <Typography component="h2" variant="h6">
            {title}
          </Typography>
          <span className="dashboard-section-count">
            {section === "waiting"
              ? data?.counts.waiting
              : section === "active"
                ? Math.max(
                    0,
                    (data?.counts.unfinished ?? 0) -
                      (data?.counts.waiting ?? 0),
                  )
                : ""}
          </span>
        </div>
        {!page?.items.length && (
          <Typography className="dashboard-empty" color="text.secondary">
            {empty}
          </Typography>
        )}
        <div className="dashboard-run-list">
          {(section === "recent" && !expandedRecent
            ? page?.items.slice(0, 5)
            : page?.items
          )?.map((run) => (
            <div className="dashboard-run" key={run.id}>
              <StatusIcon
                status={run.request ? "waiting" : run.status}
                size={22}
              />
              <div className="dashboard-run-body">
                <Button
                  className="dashboard-run-link"
                  onClick={(event) => {
                    if (event.button !== 0 || event.metaKey || event.ctrlKey)
                      return;
                    event.preventDefault();
                    onNavigate(run.project, "runs", run);
                  }}
                >
                  {run.title ||
                    stageLabel(run.workflow_key.replace(/\.ya?ml$/, ""))}{" "}
                  <span className="dashboard-run-number">#{run.number}</span>
                </Button>
                <Typography variant="body2" color="text.secondary">
                  {run.project.display_name} ·{" "}
                  {run.request
                    ? `${stageLabel(run.request.kind)} · ${stageLabel(run.request.scope_path)}`
                    : `${statusLabel(run.status)}${run.dispatch_paused ? " · Paused" : ""}`}
                </Typography>
                {section === "recent" && (
                  <Typography variant="caption" color="text.secondary">
                    {run.source_branch ?? "No branch"} ·{" "}
                    {new Date(run.ended_at ?? run.created_at).toLocaleString()}
                  </Typography>
                )}
              </div>
              <Typography
                variant="body2"
                className="dashboard-duration"
                color="text.secondary"
              >
                <ActionIcon name="clock" size={14} />{" "}
                {jobDuration(run.started_at, run.ended_at, now, run.status)}
              </Typography>
              {run.request && (
                <Button
                  variant="outlined"
                  size="small"
                  onClick={(event) => {
                    if (event.button !== 0 || event.metaKey || event.ctrlKey)
                      return;
                    event.preventDefault();
                    onNavigate(run.project, "runs", run);
                  }}
                >
                  Open request
                </Button>
              )}
            </div>
          ))}
        </div>
        {section === "recent" &&
        !expandedRecent &&
        (page?.items.length ?? 0) > 5 ? (
          <Button onClick={() => setExpandedRecent(true)}>
            Show more recent results
          </Button>
        ) : (
          page?.next_cursor && (
            <Button disabled={busy} onClick={() => more.current(section)}>
              Show more {title.toLowerCase()}
            </Button>
          )
        )}
      </Paper>
    );
  }

  return {
    fallback: null as null,
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
  };
}
export type HomeDashboardState = Extract<
  ReturnType<typeof useHomeDashboard>,
  { fallback: null }
>;
