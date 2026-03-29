# Codex Fix Prompt: Relay v1 Audit Remediation

## Context

You previously implemented the Relay application. An audit was performed against `PRODUCT_SPEC.md`, `IMPLEMENTATION_PLAN.md`, and `CODEX_PROMPT.md`. This prompt lists every discrepancy found. Fix all of them.

Read `PRODUCT_SPEC.md`, `IMPLEMENTATION_PLAN.md`, and `CODEX_PROMPT.md` before starting. The spec is the source of truth.

Do not add new features. Do not refactor working code that isn't listed here. Fix exactly what's listed below.

---

## 1. Worker / State Machine Fixes

### 1.1 Use the `starting` phase status

File: `relay/worker/phase_runner.py`

The `starting` phase status is never set. The code jumps directly from `queued` to `running`. Fix `_start_attempt` to:
1. Set phase status to `starting` before launching the subprocess.
2. Set phase status to `running` after the subprocess is confirmed launched (i.e., after `session.start()` succeeds).
3. If `session.start()` fails, transition to `retrying` or `failed` from `starting`.

### 1.2 Ghost process detection must trigger retry

File: `relay/worker/process_monitor.py`

Currently, `check_health` marks orphaned phases as `failed` and the workflow as `failed`. The spec (Section 11.4) says ghost detection should trigger retry logic. Fix:
1. When a tracked PID is dead but the phase is `running`/`starting`: mark the phase attempt as failed with `error_message="process_lost"`, but then check `can_retry()`. If retries remain, set phase status to `retrying` (not `failed`). Only set phase/workflow to `failed` if retries are exhausted.
2. Import and use `can_retry` and `backoff_seconds` from `relay/worker/retry.py`.
3. Read the run's `retry_limit` from the database to pass to `can_retry`.

### 1.3 Ghost detection: distinguish error messages on startup recovery

File: `relay/worker/process_monitor.py`

When `recover_orphans` (called on worker startup) finds dead processes, use `error_message="process_lost_worker_restart"` instead of `"process_lost"`. Keep `"process_lost"` for the periodic health check case.

### 1.4 Ghost detection: re-adopt live processes

File: `relay/worker/process_monitor.py`

Spec Section 11.4 says: if a PID is still alive on worker startup, re-adopt it. Currently the code ignores live orphans. Fix:
1. In `recover_orphans`, if a PID is alive (`psutil.pid_exists` returns True), do NOT mark it as failed.
2. Instead, register the PID in a `_monitored_pids` set so `check_health` continues to track it.
3. Add a log message: "Re-adopted orphaned process PID {pid} for phase {phase_type} (stdout/stderr monitoring unavailable)".
4. The re-adopted process has no stdout pipe, so no new log lines will be captured. This is acceptable for v1. When the process eventually exits, `check_health` will detect it's dead and handle it normally.

### 1.5 Health check interval

File: `relay/worker/main.py`

The spec says ghost/health checks run every 10 seconds, but the main loop runs `check_health` on every 1-second poll iteration. Add a timer so `check_health` is called at most once every 10 seconds:

```python
_last_health_check = 0.0

# in the main loop:
now = time.monotonic()
if now - _last_health_check >= 10.0:
    await monitor.check_health()
    _last_health_check = now
```

### 1.6 Handle PASS_WITH_WARNINGS verdict

File: `relay/worker/orchestrator.py`

Currently only exact `"PASS"` completes the workflow. `PASS_WITH_WARNINGS` falls through to the fix loop. Fix the review verdict handling (around line 300):

```python
if verdict == "PASS":
    # Clean pass
    run.status = "completed"
    ...
elif verdict == "PASS_WITH_WARNINGS":
    # Pass but with warnings -- complete with findings noted
    run.status = "completed_with_unresolved_findings"
    ...
else:
    # FAIL -- enter fix loop
    ...
```

This means `PASS_WITH_WARNINGS` completes the workflow (does not trigger the fix loop) but marks it as `completed_with_unresolved_findings` so the user can see the warnings.

---

## 2. Backend Fixes

### 2.1 WebSocket log event timestamp

File: `relay/api/ws.py`

In the `forward_log_lines` function, the `timestamp` field is hardcoded to `""`. Fix it to use the current UTC timestamp:

```python
from datetime import datetime, timezone

"timestamp": datetime.now(timezone.utc).isoformat()
```

### 2.2 Document extra DB columns

File: `relay/models/workflow_run.py`

Add comments to the `cancel_requested` and `pending_fix_prompt` columns explaining they are implementation-level signaling fields not in the product spec:

```python
cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)  # Worker signaling: API sets True, worker polls
pending_fix_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)  # Worker signaling: stores fix prompt for review-fix loop
```

Also update the Alembic migration `001_initial.py` with matching comments.

---

## 3. Frontend Fixes — Critical

### 3.1 Fix prompt editor must be pre-populated

Files: `frontend/src/pages/RunDetailPage.tsx`, `frontend/src/components/review/FixPromptEditor.tsx`

The spec says the fix prompt editor is pre-populated with the auto-generated fix prompt. Fix:
1. In `RunDetailPage.tsx`, when opening the FixPromptEditor, fetch the default fix prompt from the backend. Add a new API call: `GET /api/v1/runs/{run_id}/phases/{review_phase_id}/prompt` to get the rendered review prompt. Actually, the fix prompt should be built from review findings + spec + plan. Since the backend already builds this in `build_fix_prompt()`, expose it.
2. Add a new backend endpoint: `GET /api/v1/runs/{run_id}/review/fix-prompt` that returns the pre-built fix prompt text. Implementation: in `relay/api/workflow_control.py`, add a GET handler that reads the latest review artifacts (REVIEW_COMMENTS.json, REVIEW_SUMMARY.md, SPEC.md, IMPLEMENTATION_PLAN.md) and calls `build_fix_prompt()` from `relay/copilot/prompts.py` to render the prompt. Return `{"prompt": "..."}`.
3. In `RunDetailPage.tsx`, fetch this prompt when the user clicks "Send to Fix" and pass it as `initialValue` to `FixPromptEditor`.
4. Add the corresponding API client function in `frontend/src/api/runs.ts`.

### 3.2 Copilot CLI missing alert banner

Files: `frontend/src/components/layout/Navbar.tsx` or `frontend/src/components/layout/AppShell.tsx`

Spec says: "if Copilot CLI is not detected, the app shows a banner with instructions to install and authenticate."

1. In `AppShell.tsx` (or the top of the page layout), check the system status (`GET /api/v1/system/status`).
2. If `copilot.available` is false OR `copilot.authenticated` is false, render a shadcn `Alert` component at the top of the page (below navbar, above content):

```tsx
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { AlertTriangle } from "lucide-react";

{!copilotOk && (
  <Alert variant="destructive" className="mx-4 mt-2">
    <AlertTriangle className="h-4 w-4" />
    <AlertTitle>Copilot CLI Not Available</AlertTitle>
    <AlertDescription>
      {!copilotAvailable
        ? "GitHub Copilot CLI is not installed. Install it with: gh extension install github/gh-copilot"
        : "GitHub CLI is not authenticated. Run: gh auth login"}
    </AlertDescription>
  </Alert>
)}
```

### 3.3 Model selection: use Select dropdowns with known models

Files: `frontend/src/pages/SettingsPage.tsx`, `frontend/src/pages/NewWorkflowPage.tsx`, `frontend/src/pages/ProjectDetailPage.tsx`

All model configuration inputs currently use `Input` (free text). Replace them with `Select` dropdowns populated from the known models list.

1. Create a constant in `frontend/src/types/api.ts`:

```typescript
export const KNOWN_MODELS = [
  { id: "", name: "Default (Copilot default)" },
  { id: "gpt-4o", name: "GPT-4o" },
  { id: "gpt-4.1", name: "GPT-4.1" },
  { id: "gpt-4.1-mini", name: "GPT-4.1 Mini" },
  { id: "gpt-4.1-nano", name: "GPT-4.1 Nano" },
  { id: "claude-sonnet-4", name: "Claude Sonnet 4" },
  { id: "claude-3.5-sonnet", name: "Claude 3.5 Sonnet" },
  { id: "gemini-2.0-flash", name: "Gemini 2.0 Flash" },
  { id: "o3-mini", name: "o3-mini" },
] as const;
```

2. Replace all model `Input` fields with `Select` using proper shadcn composition:

```tsx
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";

<Select value={model} onValueChange={setModel}>
  <SelectTrigger>
    <SelectValue placeholder="Select model" />
  </SelectTrigger>
  <SelectContent>
    {KNOWN_MODELS.map((m) => (
      <SelectItem key={m.id} value={m.id}>{m.name}</SelectItem>
    ))}
  </SelectContent>
</Select>
```

### 3.4 Settings page: proper section organization and labels

File: `frontend/src/pages/SettingsPage.tsx`

Rewrite the settings page to have four clearly separated sections with headings, matching spec Section 16.2:

1. **General** — Relay data directory (display only, read from system status), Copilot CLI path (display only).
2. **Models** — Phase-to-model mapping table. Each row: phase name label + `Select` dropdown. Use the known models list.
3. **Autopilot** — Default autopilot on/off toggle with label.
4. **Retry/Loop Limits** — Two labeled number inputs: "Max retries per phase" and "Max review-fix loop iterations".

Use shadcn `Card` for each section, with a heading inside. Use `Separator` between sections. Add proper `<label>` elements for all inputs.

### 3.5 Project Configuration tab: proper settings form

File: `frontend/src/pages/ProjectDetailPage.tsx`

Replace the raw JSON dump in the Configuration tab with a real form. Structure:
1. Phase-to-model mapping table — same as Settings page but with a "Use global default" / "Override" toggle per row. When "Use global default" is selected, the Select is disabled and shows the global value.
2. Retry count override — number input with "Use global default" toggle.
3. Review-fix loop limit override — number input with "Use global default" toggle.
4. Autopilot default override — toggle with "Use global default" toggle.
5. Save button that calls `PUT /api/v1/projects/{id}/settings`.

### 3.6 WebSocket event consumption

Files: `frontend/src/hooks/useRunStatus.ts`, `frontend/src/hooks/useLogStream.ts`, `frontend/src/pages/RunsListPage.tsx`

Fix the following:
1. **`useRunStatus.ts`**: Handle `exploration_finalized`, `review_results`, and `error` events in addition to `workflow_status` and `phase_status`. On any of these events, invalidate the run query to trigger a refetch (or update the cache directly).
2. **`useLogStream.ts`**: Ensure the hook subscribes to `log` events and surfaces them. Currently this hook should be connected to `PhaseLogsTab` — verify it is.
3. **`RunsListPage.tsx`**: On mount, subscribe to all runs via `wsClient.subscribeAllRuns()`. On `workflow_status` events, invalidate the runs list query. On unmount, unsubscribe.
4. **Error events**: When an `error` WebSocket event is received, display it. The simplest approach: add a toast/notification system. If that's too complex, at minimum store errors in state and show them in the phase detail panel.

### 3.7 deleteProject API function

File: `frontend/src/api/projects.ts`

Add the missing function:

```typescript
export async function deleteProject(id: string): Promise<void> {
  await client.delete(`/projects/${id}`);
}
```

Wire it up in `ProjectDetailPage.tsx` with a delete button in the Overview tab (with a `ConfirmDialog` confirmation).

### 3.8 Review Comments tab: only show for Review phase

File: `frontend/src/components/detail-panel/PhaseDetailPanel.tsx`

The Review Comments tab is currently shown for all phases. Conditionally render it only when `phase.phase_type === "review"`:

```tsx
{phase.phase_type === "review" && (
  <TabsTrigger value="review-comments">Review Comments</TabsTrigger>
)}
```

And similarly for the `TabsContent`.

---

## 4. Frontend Fixes — Medium

### 4.1 Phase nodes: show duration

File: `frontend/src/components/workflow/PhaseNode.tsx`

For completed phases (status `succeeded`, `failed`, `cancelled`), calculate and display duration from `latest_attempt.started_at` and `latest_attempt.ended_at`:

```tsx
function formatDuration(start: string, end: string): string {
  const ms = new Date(end).getTime() - new Date(start).getTime();
  const seconds = Math.floor(ms / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const remainingSeconds = seconds % 60;
  return `${minutes}m ${remainingSeconds}s`;
}

// In the component:
{phase.latest_attempt?.ended_at && phase.latest_attempt?.started_at && (
  <span className="text-xs text-muted-foreground">
    {formatDuration(phase.latest_attempt.started_at, phase.latest_attempt.ended_at)}
  </span>
)}
```

### 4.2 Duration column in runs tables

Files: `frontend/src/pages/RunsListPage.tsx`, `frontend/src/pages/ProjectDetailPage.tsx`

Add a "Duration" column to both runs tables. Calculate from `created_at` and `updated_at` (as a proxy for completion time) for terminal-state runs. For running workflows, show elapsed time since `created_at`.

### 4.3 Status filter: multi-select

File: `frontend/src/pages/RunsListPage.tsx`

Replace the single `Select` for status filtering with a multi-select. Since shadcn doesn't ship a multi-select, implement it as a `DropdownMenu` with checkboxes:

```tsx
import { DropdownMenu, DropdownMenuCheckboxItem, DropdownMenuContent, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";

const [selectedStatuses, setSelectedStatuses] = useState<string[]>([]);

<DropdownMenu>
  <DropdownMenuTrigger asChild>
    <Button variant="outline">
      Status {selectedStatuses.length > 0 && `(${selectedStatuses.length})`}
    </Button>
  </DropdownMenuTrigger>
  <DropdownMenuContent>
    {ALL_STATUSES.map((s) => (
      <DropdownMenuCheckboxItem
        key={s}
        checked={selectedStatuses.includes(s)}
        onCheckedChange={(checked) =>
          setSelectedStatuses((prev) =>
            checked ? [...prev, s] : prev.filter((x) => x !== s)
          )
        }
      >
        {s}
      </DropdownMenuCheckboxItem>
    ))}
  </DropdownMenuContent>
</DropdownMenu>
```

When multiple statuses are selected, pass them as comma-separated to the API: `?status=running,failed`. Update the backend `GET /api/v1/runs` endpoint to accept comma-separated status values and filter with `IN`.

### 4.4 Exploration: compact graph sidebar

File: `frontend/src/pages/RunDetailPage.tsx`

When Exploration is the active phase, the spec says the graph should shrink to a compact sidebar/breadcrumb. Implement:
1. When `activePhase?.phase_type === "exploration"` and `activePhase?.status === "running"`, change the grid layout:
   - Left column: narrow (e.g., `6rem`) showing phase names + status dots vertically (no full PhaseNode rendering).
   - Right column: full chat UI.
2. After Exploration is finalized (or when viewing any other phase), revert to the standard two-column layout.

### 4.5 Review-fix loop visual arc

File: `frontend/src/components/workflow/ReviewFixLoopIndicator.tsx`

Replace the plain text counter with a visual element. Use an SVG arrow or curved connector drawn from the Review node back to the Execution node:

```tsx
{loopCount > 0 && (
  <div className="relative">
    <svg className="absolute -right-8 top-0 h-full w-8" viewBox="0 0 32 100" fill="none">
      <path
        d="M 4 100 C 4 50, 28 50, 28 0"
        stroke="currentColor"
        strokeWidth="2"
        strokeDasharray="4 2"
        className="text-muted-foreground"
      />
      <polygon points="26,4 30,0 28,8" fill="currentColor" className="text-muted-foreground" />
    </svg>
    <Badge variant="secondary" className="absolute -right-12 top-1/2 -translate-y-1/2 text-xs">
      {loopCount}/{loopLimit}
    </Badge>
  </div>
)}
```

Integrate this into `PhaseGraph.tsx` between the Execution and Review nodes.

### 4.6 Theme toggle

File: `frontend/src/components/layout/Navbar.tsx`

Add a theme toggle button to the navbar:

```tsx
import { Moon, Sun } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useSettingsStore } from "@/store/settingsStore";

const { theme, setTheme } = useSettingsStore();

<Button
  variant="ghost"
  size="icon"
  onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
>
  {theme === "dark" ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
</Button>
```

Ensure `AppShell.tsx` applies the `dark` class to the `<html>` element based on the theme store value. On first load, default to system preference.

### 4.7 Loading skeletons

Files: All page components that show loading states.

Replace `if (isLoading) return null;` patterns with skeleton layouts using the shadcn `Skeleton` component:

```tsx
import { Skeleton } from "@/components/ui/skeleton";

if (isLoading) return (
  <div className="space-y-4 p-6">
    <Skeleton className="h-8 w-48" />
    <Skeleton className="h-64 w-full" />
  </div>
);
```

Apply to: `SettingsPage`, `ProjectDetailPage`, `RunDetailPage`, `RunsListPage`, `ProjectsListPage`.

### 4.8 Confirmation dialogs for destructive actions

Files: `frontend/src/components/review/ReviewApprovalBar.tsx`, `frontend/src/pages/ProjectDetailPage.tsx`

Use the existing `ConfirmDialog` component before cancel and delete actions:

1. "Cancel Workflow" button in `ReviewApprovalBar`: wrap with `ConfirmDialog` — "Are you sure you want to cancel this workflow? The running process will be killed immediately."
2. "Delete Project" button (once added per 3.7): wrap with `ConfirmDialog` — "Are you sure you want to remove this project? This does not delete project files."

### 4.9 Project cards: fix git indicator

File: `frontend/src/pages/ProjectsListPage.tsx`

Replace the incorrect `StatusBadge` usage (which maps `is_git_repo` to `succeeded`/`queued`) with a simple label:

```tsx
<Badge variant={project.is_git_repo ? "default" : "secondary"}>
  {project.is_git_repo ? "Git" : "Local"}
</Badge>
```

### 4.10 Project Overview: active runs summary

File: `frontend/src/pages/ProjectDetailPage.tsx`

In the Overview tab, add an active runs summary. Fetch runs for this project (`GET /api/v1/runs?project_id={id}&limit=100`) and display:
- Count of active runs (status `running` or `waiting_for_user`)
- Status badges for each active run

### 4.11 Navbar links: use Button variant="ghost"

File: `frontend/src/components/layout/Navbar.tsx`

Replace bare `NavLink` elements with `Button` `variant="ghost"` wrapped in links, per CODEX_PROMPT.md:

```tsx
<NavLink to="/projects">
  {({ isActive }) => (
    <Button variant="ghost" className={isActive ? "bg-accent" : ""}>
      Projects
    </Button>
  )}
</NavLink>
```

---

## 5. shadcn/ui Composition Fixes

### 5.1 Dialog composition

Files: All files using `Dialog` (e.g., `ProjectsListPage.tsx`)

Replace raw `<div>` children inside `<Dialog>` with proper shadcn subcomponents:

```tsx
<Dialog open={open} onOpenChange={setOpen}>
  <DialogContent>
    <DialogHeader>
      <DialogTitle>Add Project</DialogTitle>
    </DialogHeader>
    {/* form content */}
    <DialogFooter>
      <Button onClick={handleSubmit}>Add</Button>
    </DialogFooter>
  </DialogContent>
</Dialog>
```

### 5.2 Table composition

Files: `RunsListPage.tsx`, `ReviewCommentsTab.tsx`, `ProjectDetailPage.tsx`, `AttemptHistoryTab.tsx`

Replace raw `<thead>`, `<tbody>`, `<tr>`, `<th>`, `<td>` with shadcn Table subcomponents:

```tsx
<Table>
  <TableHeader>
    <TableRow>
      <TableHead>Name</TableHead>
      <TableHead>Status</TableHead>
    </TableRow>
  </TableHeader>
  <TableBody>
    <TableRow>
      <TableCell>...</TableCell>
      <TableCell>...</TableCell>
    </TableRow>
  </TableBody>
</Table>
```

### 5.3 Tabs composition

Files: `PhaseDetailPanel.tsx`, `ProjectDetailPage.tsx`

Replace the custom `tabs` array prop pattern with standard shadcn Tabs composition:

```tsx
<Tabs defaultValue="summary">
  <TabsList>
    <TabsTrigger value="summary">Summary</TabsTrigger>
    <TabsTrigger value="prompt">Prompt</TabsTrigger>
    <TabsTrigger value="logs">Logs</TabsTrigger>
    {phase.phase_type === "review" && (
      <TabsTrigger value="review-comments">Review Comments</TabsTrigger>
    )}
    <TabsTrigger value="attempts">Attempts</TabsTrigger>
  </TabsList>
  <TabsContent value="summary"><PhaseSummaryTab ... /></TabsContent>
  <TabsContent value="prompt"><PhasePromptTab ... /></TabsContent>
  <TabsContent value="logs"><PhaseLogsTab ... /></TabsContent>
  {phase.phase_type === "review" && (
    <TabsContent value="review-comments"><ReviewCommentsTab ... /></TabsContent>
  )}
  <TabsContent value="attempts"><AttemptHistoryTab ... /></TabsContent>
</Tabs>
```

### 5.4 Sheet composition

Files: `ContextPanel.tsx`, `FixPromptEditor.tsx`

Replace raw children inside `<Sheet>` with proper subcomponents:

```tsx
<Sheet open={open} onOpenChange={onClose}>
  <SheetContent>
    <SheetHeader>
      <SheetTitle>Context Files</SheetTitle>
    </SheetHeader>
    {/* content */}
  </SheetContent>
</Sheet>
```

### 5.5 Select composition

Files: All files currently using the simplified `Select` wrapper.

Replace with standard shadcn Select composition using `SelectTrigger`, `SelectValue`, `SelectContent`, `SelectItem` as shown in section 3.3 above.

---

## 6. Test Fixes

### 6.1 E2E test: full autopilot workflow

File: `tests/e2e/test_full_workflow_autopilot.py`

Rewrite to actually drive a full workflow:
1. Create a project (use a temp directory).
2. Create a run with `autopilot=True`.
3. Inject `FakeCopilotSession` with canned responses for each phase:
   - Exploration: canned chat response + finalization response (planning prompt markdown)
   - Planning: write SPEC.md and IMPLEMENTATION_PLAN.md to artifact dir
   - Critique: write IMPLEMENTATION_PLAN_CRITIQUED.md
   - Correction: write corrected IMPLEMENTATION_PLAN.md
   - Execution: (no artifacts needed, just exit 0)
   - Review: output with `relay-review-comments` JSON block and REVIEW_SUMMARY.md with verdict PASS
4. Start the worker (or call worker functions directly).
5. Send exploration messages via API.
6. Finalize exploration via API.
7. Wait for workflow to reach `completed` status (poll with timeout).
8. Assert: workflow status is `completed`, all 6 phases are `succeeded`, artifacts exist on disk.

### 6.2 E2E test: full manual workflow

File: `tests/e2e/test_full_workflow_manual.py`

Rewrite to drive a manual workflow:
1. Same setup as autopilot but with `autopilot=False`.
2. After exploration finalization, assert workflow is `waiting_for_user`.
3. Call `POST /runs/{id}/advance` to start Planning.
4. Wait for Plan Critique to complete, assert `waiting_for_user`.
5. Call `POST /runs/{id}/advance` to continue to Plan Correction.
6. Wait for Review to complete, assert `waiting_for_user`.
7. Call `POST /runs/{id}/review/approve`.
8. Assert workflow is `completed`.

### 6.3 Unit test: state machine — expand coverage

File: `tests/unit/test_state_machine.py`

Add tests for:
- All invalid workflow transitions (e.g., `completed -> running` should fail).
- All invalid phase transitions (e.g., `succeeded -> running` should fail).
- `cancelled -> running` transition (valid per spec Section 9.2).
- `stale -> queued` transition.
- `failed -> queued` transition.
- `waiting_for_user -> completed` transition.
- `waiting_for_user -> completed_with_unresolved_findings` transition.

### 6.4 Unit test: retry — test 120s cap

File: `tests/unit/test_retry.py`

Add a test that verifies the backoff caps at 120 seconds:
```python
def test_backoff_caps_at_120():
    assert backoff_seconds(6) == 120  # 5 * 2^5 = 160, capped to 120
    assert backoff_seconds(7) == 120
    assert backoff_seconds(100) == 120
```

### 6.5 Unit test: artifact parser — malformed input

File: `tests/unit/test_artifact_parser.py`

Add tests for:
- Malformed JSON inside the sentinel block (should return `parsed=False`).
- Missing sentinel block entirely (should return `parsed=False`, empty comments).
- Valid JSON but wrong structure (missing required fields).
- Multiple sentinel blocks (should use the first one).
- Verdict parsing: test `PASS`, `FAIL`, `PASS_WITH_WARNINGS`, missing verdict section, garbled verdict text.

### 6.6 Unit test: settings resolution — precedence chain

File: `tests/unit/test_settings_resolution.py`

Add tests for the 4-level precedence chain:
- Run override beats project override.
- Project override beats global setting.
- Global setting beats app default.
- Null/missing override falls through to next level.
- Empty string model is preserved (means "use default"), not treated as missing.

### 6.7 Integration test: orchestrator — expand coverage

File: `tests/integration/test_worker_orchestrator.py`

Add tests for:
- Full autopilot workflow with FakeCopilotSession completing all phases.
- Review-fix loop: FakeCopilotSession returns FAIL verdict twice then PASS. Verify loop count increments and workflow completes.
- Review-fix loop limit: FakeCopilotSession always returns FAIL. Verify workflow ends as `completed_with_unresolved_findings` after reaching limit.
- Retry: FakeCopilotSession fails on attempt 1, succeeds on attempt 2. Verify retry works and phase succeeds.
- Cancel: Start a workflow, cancel it mid-phase, verify statuses.
- Rerun from failed phase: Fail a phase, rerun it, verify downstream phases marked stale.

---

## 7. Backend Endpoint Addition

### 7.1 Fix prompt preview endpoint

File: `relay/api/workflow_control.py`

Add:
```python
@router.get("/runs/{run_id}/review/fix-prompt")
async def get_fix_prompt_preview(run_id: str, db: AsyncSession = Depends(get_db)):
    """Return the pre-built fix prompt for the review-fix loop."""
    # Read latest review artifacts
    # Call build_fix_prompt() from relay/copilot/prompts.py
    # Return {"prompt": rendered_prompt_string}
```

This is needed by the frontend fix prompt editor (Section 3.1).

---

## 8. Verification Checklist

After all fixes, verify:
1. `uv run pytest tests/unit/` — all unit tests pass
2. `uv run pytest tests/integration/` — all integration tests pass
3. `uv run pytest tests/e2e/` — both E2E tests pass (these now actually test full workflows)
4. `cd frontend && npm run build` — frontend builds without errors
5. `docker build .` — Docker image builds
6. No regressions: existing passing tests still pass
