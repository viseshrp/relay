export interface LocationState {
  view: "author" | "runs";
  project: string | null;
  workflow: string | null;
  run: string | null;
  interaction: string | null;
}

const LOCATION_KEY = "relay.location";

export function readLocation(): LocationState {
  // ?view=runs&run=abc&interaction=42 opens that request; a plain reload uses the saved selection.
  const query = window.location.search || localStorage.getItem(LOCATION_KEY) || "";
  const parameters = new URLSearchParams(query);
  return {
    view: parameters.get("view") === "runs" || parameters.has("run") ? "runs" : "author",
    project: parameters.get("project"),
    workflow: parameters.get("workflow"),
    run: parameters.get("run"),
    interaction: parameters.get("interaction"),
  };
}

export function saveLocation(location: LocationState, replace = false): void {
  const query = new URLSearchParams({ view: location.view });
  for (const key of ["project", "workflow", "run", "interaction"] as const) {
    const value = location[key];
    if (value) query.set(key, value);
  }
  const search = `?${query.toString()}`;
  localStorage.setItem(LOCATION_KEY, search);
  if (search !== window.location.search) {
    if (replace) window.history.replaceState(null, "", search);
    else window.history.pushState(null, "", search);
  }
}

export function projectPath(path: string, projectId?: string | null): string {
  // /api/workflows/review + project "abc" -> /api/workflows/review?project=abc.
  if (!projectId) return path;
  return `${path}${path.includes("?") ? "&" : "?"}project=${encodeURIComponent(projectId)}`;
}

export function stageLabel(scope: string): string {
  // root.human_walkthrough -> Human walkthrough; root.build#2.check -> Check (iteration 2).
  const parts = scope.split(".");
  const raw = parts[parts.length - 1].replace(/#\d+$/, "").replace(/[_-]+/g, " ");
  const label = raw.charAt(0).toUpperCase() + raw.slice(1);
  const iteration = scope.match(/#(\d+)/)?.[1];
  return iteration ? `${label} (iteration ${iteration})` : label;
}

export function statusLabel(status: string): string {
  return ({
    pending: "Not started", ready: "Ready", dispatched: "Starting", running: "In progress",
    waiting: "Needs your input", paused_wait: "Needs your input", succeeded: "Complete",
    failed: "Needs attention", skipped: "Skipped", canceled: "Stopped", canceling: "Stopping",
    failing: "Finishing after an error", interrupted: "Resuming after restart",
  } as Record<string, string>)[status] ?? status;
}
