import { statusPresentation } from "./status";
export interface LocationState {
  view: "home" | "workflows" | "runs" | "settings";
  project: string | null;
  workflow: string | null;
  run: string | null;
  interaction: string | null;
  job: string | null;
}

const LOCATION_KEY = "relay.location";

export function readLocation(): LocationState {
  // Explicit workspace links remain authoritative; the bare root opens Home.
  let stored = "";
  try {
    stored = localStorage.getItem(LOCATION_KEY) ?? "";
  } catch {
    /* Navigation remains available when browser storage is disabled. */
  }
  const query = window.location.search;
  const parameters = new URLSearchParams(query);
  const remembered = new URLSearchParams(stored);
  return {
    view:
      parameters.get("view") === "home" || !query
        ? "home"
        : parameters.get("view") === "settings"
          ? "settings"
          : parameters.get("view") === "runs" || parameters.has("run")
            ? "runs"
            : parameters.get("view") === "workflows" ||
                parameters.has("workflow")
              ? "workflows"
              : "home",
    project:
      parameters.get("project") ?? (!query ? remembered.get("project") : null),
    workflow: parameters.get("workflow"),
    run: parameters.get("run"),
    interaction: parameters.get("interaction"),
    job: parameters.get("job"),
  };
}

export function saveLocation(location: LocationState, replace = false): void {
  const query = new URLSearchParams({ view: location.view });
  for (const key of [
    "project",
    "workflow",
    "run",
    "interaction",
    "job",
  ] as const) {
    const value = location[key];
    if (value) query.set(key, value);
  }
  const search = `?${query.toString()}`;
  try {
    localStorage.setItem(LOCATION_KEY, search);
  } catch {
    /* The URL remains authoritative without browser storage. */
  }
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

export function viewHref(
  view: LocationState["view"],
  project: string | null,
  values: Record<string, string> = {},
): string {
  const query = new URLSearchParams({ view, ...values });
  if (project) query.set("project", project);
  return `/?${query}`;
}

export function stageLabel(scope: string): string {
  // root.release.verify_release -> Verify release.
  const raw = scope.split(".").at(-1)!.replace(/[_-]+/g, " ");
  return raw.charAt(0).toUpperCase() + raw.slice(1);
}

export function statusLabel(status: string): string {
  return statusPresentation(status).label;
}
