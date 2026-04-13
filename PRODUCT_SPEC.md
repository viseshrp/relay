# Relay v1 Product Specification

**Version:** 1.0
**Date:** 2026-03-28

---

## Table of Contents

1. [Overview](#1-overview)
2. [Goals and Non-Goals](#2-goals-and-non-goals)
3. [User Journeys](#3-user-journeys)
4. [Workflow Model](#4-workflow-model)
5. [Phase Specifications](#5-phase-specifications)
6. [Workflow State Machine](#6-workflow-state-machine)
7. [Autopilot and Approval Model](#7-autopilot-and-approval-model)
8. [Reruns, Retries, and Failure Handling](#8-reruns-retries-and-failure-handling)
9. [Cancellation](#9-cancellation)
10. [Backend Architecture](#10-backend-architecture)
11. [Worker and Monitoring Architecture](#11-worker-and-monitoring-architecture)
12. [Persistence Model](#12-persistence-model)
13. [Artifact Layout](#13-artifact-layout)
14. [API Surface](#14-api-surface)
15. [WebSocket Event Model](#15-websocket-event-model)
16. [UI Structure](#16-ui-structure)
17. [Settings and Configuration Model](#17-settings-and-configuration-model)
18. [Copilot CLI Integration Contract](#18-copilot-cli-integration-contract)
19. [Projects and Runs](#19-projects-and-runs)
20. [Concurrency Model](#20-concurrency-model)
21. [Edge-Case Decisions](#21-edge-case-decisions)
22. [Assumptions](#22-assumptions)
23. [Glossary](#23-glossary)

---

## 1. Overview

Relay is a self-hostable web application that orchestrates multi-phase AI coding workflows. It acts as a control plane for chained AI coding sessions, where each workflow progresses through a fixed sequence of phases (Exploration, Planning, Plan Critique, Plan Correction, Execution, Review) with each phase spawning and managing one or more GitHub Copilot CLI subprocess sessions.

The UI follows a GitHub Actions-style paradigm: a workflow graph visualization with a detail panel, live streaming logs, and persistent run history.

Relay ships as a single Docker image built on `uv`, run in different modes (backend API server, frontend, worker) via command-line flags. The Docker image includes GitHub Copilot CLI (`gh` + Copilot extension) pre-installed. Users volume-mount their project folders and `gh` auth credentials into the container.

---

## 2. Goals and Non-Goals

### Goals

- Provide a structured, repeatable orchestration layer on top of AI coding tools
- Support a full plan-critique-execute-review cycle with automated looping
- Deliver a self-hostable solution with minimal infrastructure requirements (single Docker image, SQLite)
- Real-time visibility into workflow progress via WebSocket-driven UI
- Support both fully-automated (autopilot) and human-in-the-loop execution modes
- Track all artifacts, prompts, and logs for auditability and debugging
- Allow concurrent workflow execution across multiple projects

### Non-Goals

- **No branching/parallel workflows in v1.** Linear phase sequences only.
- **No user authentication/authorization in v1.** Single-user or trusted-network deployment assumed.
- **No cloud deployment targets.** Self-hosted via Docker only.
- **No Cursor CLI support in v1.** Architecture should not preclude it, but no explicit abstraction layer is required yet.
- **No automatic Copilot CLI installation or credential management.** User handles setup externally.
- **No mobile-responsive UI.** Desktop browser only.
- **No collaborative multi-user features.** Single operator at a time.
- **No plugin/extension system.** Phase definitions are hardcoded for v1.
- **No CI/CD integration.** Relay is a standalone tool.

---

## 3. User Journeys

### 3.1 First-Time Setup

1. User pulls and runs the Relay Docker image.
2. User opens the web UI in a browser (default `http://localhost:8080`).
3. On first load, if Copilot CLI is not detected, the app shows a banner with instructions to install and authenticate Copilot CLI on the host.
4. User navigates to Settings and configures global default model mappings for each phase.
5. User adds a project by entering a local folder path. The app validates the path exists, detects if it is a git repo, and stores the project.

### 3.2 Running a Full Workflow (Autopilot)

1. User navigates to a project page, clicks "New Workflow."
2. User fills in workflow name. Optionally overrides models or other settings in the advanced section.
3. Workflow starts. Exploration phase opens in a chat UI.
4. User describes the problem, goals, constraints, preferred stack, and desired output through conversational messages. The app streams Copilot CLI responses live.
5. User selects relevant files/folders in the right-side context panel.
6. User clicks "Finalize Exploration." The app generates a Markdown planning prompt artifact and saves it.
7. With autopilot ON, the remaining phases execute automatically:
   - Planning produces SPEC.md and IMPLEMENTATION_PLAN.md
   - Plan Critique annotates the plan
   - Plan Correction produces a corrected plan
   - Execution implements and validates the code
   - Review evaluates the result
8. If Review finds issues, the review-fix loop engages automatically (up to the configured max).
9. Workflow completes. User sees the final status and can browse all phase outputs, prompts, and logs.

### 3.3 Running a Workflow (Non-Autopilot)

1. Steps 1-6 same as autopilot.
2. After Exploration finalization, the planning prompt is shown read-only. User clicks "Start Planning" to proceed.
3. Planning, Plan Critique run. Workflow pauses after Plan Critique.
4. User reviews the critique, clicks "Continue" to proceed to Plan Correction.
5. Plan Correction and Execution run. Workflow pauses after Review.
6. User reviews findings. User can either:
   - Approve and mark workflow complete, OR
   - Edit the fix prompt and send findings back to Execution.
7. If sent back, Execution reruns with the fix prompt. Review runs again. This repeats until user approves or max loop count is reached.

### 3.4 Handling a Phase Failure

1. A phase fails after exhausting retries.
2. Workflow is marked failed. UI shows the failed phase highlighted.
3. User clicks the failed phase and sees attempt history with logs.
4. User can:
   - Click "Restart from this phase" to retry within the same run (same branch, same run ID).
   - Click "New Workflow" to start fresh (new run ID, new branch if git).

### 3.5 Browsing Past Runs

1. User navigates to the Runs page (global) or a project's Runs tab.
2. Runs are listed newest-first, filterable by project and status.
3. Clicking a run opens the run detail view with the phase graph and detail panel.
4. All past phases, prompts, logs, and artifacts are browsable.

---

## 4. Workflow Model

### 4.1 Core Constraints

- **Linear only.** Phases execute in a fixed order.
- **One active phase per workflow.** No parallelism within a workflow.
- **Multiple workflows may run concurrently** across different projects (or the same project with caveats).
- **Exploration is always first** and is the only interactive/chat phase.
- **Every workflow starts with a blank Exploration.** No cloning or templating in v1.

### 4.2 Phase Order

```
Exploration -> Planning -> Plan Critique -> Plan Correction -> Execution -> Review
                                                                  ^          |
                                                                  |__________|
                                                                 (review-fix loop)
```

### 4.3 Session Reuse

| Phase            | Copilot Session |
|------------------|-----------------|
| Exploration      | Fresh           |
| Planning         | Fresh           |
| Plan Critique    | Fresh           |
| Plan Correction  | Reuses Planning session |
| Execution        | Fresh (initial); Reused for fix loops |
| Review           | Fresh (initial); Fresh for each re-review |

**Assumption:** "Reusing a session" means sending follow-up messages to the same Copilot CLI subprocess that has not been terminated. If the subprocess has exited (e.g., due to a crash), a new subprocess is started and the prior conversation context is lost. The app does NOT attempt to replay conversation history into a new subprocess.

---

## 5. Phase Specifications

### 5.1 Exploration

**Purpose:** Interactive discovery of the problem, goals, and constraints.

**Behavior:**
- Chat-style UI with streaming responses.
- Uses Copilot CLI in Ask mode (read-only, no file modifications).
- Single continuous chat thread per workflow. Messages are appended, never edited or deleted.
- Messages are saved automatically to the database as the user sends them.
- Copilot responses stream live to the UI via WebSocket.
- User cannot interrupt/stop a response mid-stream. The send button is disabled while a response is streaming.
- User manually finalizes Exploration by clicking a "Finalize" button.
- Finalize button is disabled while a response is streaming.
- Once finalized, the chat becomes read-only. No reopening, editing, or appending.

**Context Panel (right side):**
- User can browse the project file tree and select files/folders.
- Selections are stored as paths (not contents). Folder selections are stored as folder paths, not expanded.
- Selected paths are carried forward to all subsequent phases as part of every phase prompt.
- Context selections are immutable after Exploration is finalized.

**Output Artifact:** A Markdown file (`.relay/<run-id>/exploration/planning_prompt.md`) containing:
- Problem statement
- Goals
- Constraints
- Preferred stack
- Files to read (the selected context paths)
- Desired output

**Generation:** The app constructs this artifact by prompting the Exploration Copilot session to summarize the conversation into the structured format above. The app provides the template/structure; the model fills it in.

**Assumption:** The planning prompt artifact generation is the final message sent to the Exploration Copilot session before it is terminated. If the generation fails (Copilot error), it follows the standard retry logic.

**Post-Finalization Flow:**
- The generated planning prompt is displayed read-only in the UI.
- In autopilot mode: Planning starts automatically.
- In non-autopilot mode: UI shows a "Start Planning" button. User triggers it manually.

### 5.2 Planning

**Purpose:** Produce a specification and implementation plan.

**Behavior:**
- Fresh Copilot CLI session in Agent mode.
- Receives: the planning prompt artifact + selected context paths.
- Working directory: the project folder (on the workflow branch if git).

**Output Artifacts:**
- `SPEC.md` — written by the model into the repo artifact folder
- `IMPLEMENTATION_PLAN.md` — written by the model into the repo artifact folder

The internal structure of these files is model-controlled. The app does not enforce or validate their internal format.

**Completion Detection:** The phase is considered complete when the Copilot CLI subprocess exits with code 0. The app then verifies that both `SPEC.md` and `IMPLEMENTATION_PLAN.md` exist in the expected artifact folder. If either is missing, the phase is marked as failed (triggering retry logic).

### 5.3 Plan Critique

**Purpose:** Independent critical review of the implementation plan.

**Behavior:**
- Fresh Copilot CLI session in Agent mode.
- Receives: `SPEC.md`, `IMPLEMENTATION_PLAN.md`, planning prompt, selected context paths.
- Prompt instructs the model to annotate `IMPLEMENTATION_PLAN.md` inline with critique comments.

**Output Artifact:**
- `IMPLEMENTATION_PLAN_CRITIQUED.md` — the original plan text with inline critique comments clearly delimited (e.g., using `> [CRITIQUE]: ...` block-quote markers).

**Assumption:** The app prompt instructs the model to use a specific delimiter format for critique comments so they are visually and programmatically distinguishable from original plan text. The exact delimiter is: `<!-- CRITIQUE: ... -->` HTML comments for machine parsing, plus rendered `> **Critique:** ...` blockquotes for human reading.

### 5.4 Plan Correction

**Purpose:** Incorporate critique feedback into a corrected plan.

**Behavior:**
- Reuses the Planning session (same Copilot subprocess).
- Receives: the critiqued plan as a follow-up message.
- Prompt instructs the model to address the critique and produce a clean corrected plan.

**Output Artifact:**
- `IMPLEMENTATION_PLAN.md` — overwritten in place with the corrected version. The prior version is preserved in the attempt history artifact folder.

**Assumption:** If the Planning session subprocess has died between Planning and Plan Correction, a new subprocess is started. The new session receives: the original planning prompt, the original `SPEC.md` and `IMPLEMENTATION_PLAN.md` (as context), and the critique, with instructions to produce a corrected plan. This is a degraded but functional fallback.

### 5.5 Execution

**Purpose:** Implement the plan and validate the result.

**Behavior:**
- Fresh Copilot CLI session in Agent mode (for initial execution).
- Receives: `SPEC.md`, corrected `IMPLEMENTATION_PLAN.md`, selected context paths.
- The model implements the plan, making file changes in the working tree.
- After implementation, the model runs local validation (build, test, lint) as instructed by the prompt.
- Changes are left uncommitted in the working tree.

**Git Behavior:**
- If the project is a git repo: a workflow-specific branch is created before Execution starts (branch naming: `relay/<run-id>`). The branch is created from the project's current HEAD at workflow creation time.
- If not a git repo: changes are made directly in the project folder.

**Output:** Modified files in the working tree. No explicit artifact file, but logs capture all actions taken.

**Completion Detection:** Copilot CLI subprocess exits with code 0. The app does not validate what was actually implemented — that is Review's job.

### 5.6 Review

**Purpose:** Evaluate the implementation against the spec and plan.

**Behavior:**
- Fresh Copilot CLI session in Agent mode (fresh for each review cycle).
- Receives: `SPEC.md`, corrected `IMPLEMENTATION_PLAN.md`, selected context paths, plus a prompt to review the current working tree state.
- Outputs structured review comments and a summary report.

**Output Artifacts:**
- `REVIEW_COMMENTS.json` — structured review comments in JSON format:
  ```json
  [
    {
      "file": "src/main.py",
      "line": 42,
      "severity": "error|warning|suggestion",
      "comment": "..."
    }
  ]
  ```
  If the model cannot tie a comment to a specific file/line, it uses `"file": null, "line": null`.
- `REVIEW_SUMMARY.md` — guided by an app-provided template:
  ```markdown
  ## Summary
  ...
  ## Deviations from Spec
  ...
  ## Risks
  ...
  ## Suggestions
  ...
  ## Verdict
  PASS | FAIL | PASS_WITH_WARNINGS
  ```

**Assumption:** The app prompt for Review includes explicit instructions to output the JSON comments block in a fenced code block with a known sentinel (e.g., ```` ```relay-review-comments ... ``` ````) and to follow the summary template. The app parses these from the Copilot CLI stdout. If parsing fails, the raw output is saved as `REVIEW_RAW.md` and the phase is still considered succeeded (with a UI indicator that structured parsing failed).

**Verdict Determination:** The app reads the `## Verdict` section of `REVIEW_SUMMARY.md`. If it contains `PASS`, the review is clean. Any other value triggers the review-fix loop (if in autopilot) or presents the user with approve/fix options (if not).

### 5.7 Review-Fix Loop

When Review produces findings (verdict is not PASS):

**Autopilot mode:**
1. App constructs a fix prompt from: review findings (`REVIEW_COMMENTS.json` + `REVIEW_SUMMARY.md`), `SPEC.md`, corrected `IMPLEMENTATION_PLAN.md`.
2. Fix prompt is sent to the Execution session (reused subprocess).
3. After Execution completes, a fresh Review session evaluates again.
4. Loop continues until Review passes OR max loop count is reached.

**Non-autopilot mode:**
1. Workflow pauses. UI displays review findings.
2. User can:
   - Click "Approve" to mark workflow complete (status: `completed_with_unresolved_findings` if there were findings).
   - Click "Send to Fix" which opens the fix prompt in an editable text area. User edits if desired, then confirms.
3. After fix, Review runs again. Workflow pauses again after Review.

**Max loop reached:**
- Workflow status: `completed_with_unresolved_findings`.
- UI shows a clear indicator: "Review-fix loop limit reached (N/N). Unresolved findings remain."
- The workflow is NOT marked as failed.

---

## 6. Workflow State Machine

### 6.1 Workflow Statuses

| Status | Description |
|--------|-------------|
| `queued` | Workflow created, waiting for worker capacity |
| `running` | At least one phase is active |
| `waiting_for_user` | Paused at a non-autopilot approval point |
| `completed` | All phases finished, review passed |
| `completed_with_unresolved_findings` | Completed but review findings remain |
| `failed` | A phase failed after exhausting retries |
| `cancelled` | User cancelled the workflow |

**Assumption:** Added `waiting_for_user` status to distinguish paused workflows from actively running ones. This is necessary for correct UI rendering and for the worker to know not to schedule work for this workflow.

### 6.2 Phase Statuses

| Status | Description |
|--------|-------------|
| `queued` | Phase is next in line |
| `starting` | Subprocess is being spawned |
| `running` | Subprocess is active |
| `retrying` | Failed, retry scheduled (with backoff timer) |
| `succeeded` | Phase completed successfully |
| `failed` | Phase failed after all retries exhausted |
| `cancelled` | Killed due to workflow cancellation |
| `stale` | A predecessor phase was rerun, invalidating this result |
| `waiting_for_user` | Phase completed but needs user input to proceed |

### 6.3 State Transitions

```
WORKFLOW:
  queued -> running                              (worker picks up)
  running -> waiting_for_user                    (non-autopilot pause point)
  waiting_for_user -> running                    (user approves/continues)
  running -> completed                           (review passes)
  running -> completed_with_unresolved_findings  (loop limit reached)
  running -> failed                              (phase fails after retries)
  running -> cancelled                           (user cancels)
  waiting_for_user -> cancelled                  (user cancels)
  failed -> running                              (user reruns from a phase)

PHASE:
  queued -> starting                             (worker begins phase)
  starting -> running                            (subprocess launched)
  running -> succeeded                           (exit code 0 + validation)
  running -> retrying                            (exit code != 0, retries left)
  retrying -> starting                           (retry timer elapsed)
  running -> failed                              (exit code != 0, no retries left)
  running -> cancelled                           (workflow cancelled)
  succeeded -> stale                             (earlier phase rerun)
  failed -> queued                               (user reruns this phase)
  stale -> queued                                (rerun reaches this phase)
```

---

## 7. Autopilot and Approval Model

### 7.1 Autopilot Toggle

- Persistent toggle in the navbar, saved to user settings.
- Affects all new phase transitions; does not retroactively change paused workflows.
- Can be toggled mid-workflow. The new setting applies to the next transition.

### 7.2 Pause Points (Non-Autopilot)

| After Phase | What Happens |
|-------------|-------------|
| Exploration finalized | Show planning prompt, wait for user to click "Start Planning" |
| Plan Critique succeeded | Show critique, wait for user to click "Continue to Plan Correction" |
| Review succeeded | Show findings, wait for user to approve or send to fix |

**In autopilot mode:** All these transitions happen automatically with no pause.

### 7.3 User Actions at Pause Points

**After Exploration:**
- "Start Planning" — advance to Planning phase

**After Plan Critique:**
- "Continue" — advance to Plan Correction

**After Review:**
- "Approve & Complete" — mark workflow as `completed` (or `completed_with_unresolved_findings` if there were findings)
- "Send to Fix" — opens editable fix prompt, then sends to Execution
- "Cancel Workflow" — cancels the workflow

---

## 8. Reruns, Retries, and Failure Handling

### 8.1 Automatic Retries (Infrastructure/Runtime Failures)

- When a Copilot CLI subprocess exits with a non-zero code, or crashes, or times out:
  - Retry with exponential backoff: base delay 5s, multiplier 2x, max delay 120s.
  - Formula: `delay = min(5 * 2^(attempt-1), 120)` seconds. So: 5s, 10s, 20s, 40s, 80s.
  - Default max retries: 5 (meaning up to 6 total attempts including the initial one).
  - Configurable globally, per-project, and per-run.
- Each retry attempt is recorded with its own logs and metadata.
- If all retries are exhausted, the phase status becomes `failed` and the workflow status becomes `failed`.

### 8.2 User-Initiated Reruns After Failure

**Restart from failed phase:**
- Same workflow run, same run ID, same branch.
- Phase status resets to `queued`. Previous attempt history is preserved.
- Retry counter resets to 0 for the rerun.
- Downstream phases (if any succeeded before) are marked `stale`.

**Restart whole workflow (new workflow):**
- New run ID, new branch (if git), fresh Exploration.
- The failed run remains in history for reference.

### 8.3 Rerun from Earlier Phase

- User can restart from any phase that has been reached (not just the failed one).
- All downstream phase results are marked `stale`.
- The rerun phase starts fresh (new attempt appended to attempt history).
- The workflow graph shows latest attempt status per phase.

### 8.4 Attempt History

- Every phase execution (including retries and reruns) is recorded as an attempt.
- Attempts are numbered sequentially: attempt 1, attempt 2, etc.
- The graph node shows the latest attempt's status.
- The detail panel has an attempt selector to view any past attempt's logs and artifacts.

---

## 9. Cancellation

### 9.1 Mechanics

1. User clicks "Cancel Workflow" in the UI.
2. Backend sends a cancel command to the worker.
3. Worker immediately kills the currently running subprocess (SIGKILL on Unix / TerminateProcess on Windows).
4. Phase status becomes `cancelled`.
5. Workflow status becomes `cancelled`.
6. Working tree changes are left as-is (not rolled back).

### 9.2 Post-Cancellation

- No resume from cancelled state.
- User options:
  - Rerun from a specific phase (creates a continuation within the same run).
  - Create a new workflow.

**Assumption:** "Rerun from a phase" after cancellation follows the same mechanics as rerun after failure. The cancelled phase gets a new attempt. The workflow status transitions from `cancelled` back to `running`.

---

## 10. Backend Architecture

### 10.1 Technology Stack

- **Framework:** FastAPI (async)
- **Database:** SQLite via aiosqlite with SQLAlchemy async ORM
- **Real-time:** WebSockets (native FastAPI)
- **Task queue:** None. Worker polls database directly.
- **Process model:** Single Docker image, three run modes:
  - `relay serve` — FastAPI server (API + WebSocket + static frontend)
  - `relay worker` — Worker/supervisor process
  - `relay dev` — Runs both server and worker in one process (development mode)

### 10.2 Server Process

Responsibilities:
- Serve REST API endpoints
- Serve frontend static files
- Manage WebSocket connections
- Validate requests, write to database
- Broadcast phase/workflow status changes to connected WebSocket clients

### 10.3 Communication: Server <-> Worker

- **Database as message bus.** No direct IPC.
- Server writes commands (start workflow, cancel workflow) as rows/flags in the database.
- Worker polls the database for pending work at a configurable interval (default: 1 second).
- Worker writes status updates, logs, and results back to the database.
- Server detects changes via polling or database triggers and pushes to WebSocket clients.

**Assumption:** For v1, simple polling is sufficient. The server polls for status changes every 1 second to push WebSocket updates. This introduces up to 1 second latency for status transitions, which is acceptable.

**Log Streaming Exception:** For live log streaming, the worker writes log lines to a shared log file (one per phase attempt) on the filesystem. The server tails this file and streams lines to WebSocket clients. This avoids high-frequency database writes for log lines.

### 10.4 API Server Startup

On startup, the server:
1. Runs database migrations (auto-apply pending migrations).
2. Checks for Copilot CLI availability and reports status (does not block startup).
3. Begins serving requests.

---

## 11. Worker and Monitoring Architecture

### 11.1 Worker Process

The worker is a long-running Python process that:
1. Polls the database every 1 second for actionable work.
2. Manages Copilot CLI subprocesses via `subprocess.Popen`.
3. Monitors subprocess health (PID liveness, stdout/stderr).
4. Handles retries, backoff, and cancellation.
5. Updates the database with status transitions, exit codes, and timing.

### 11.2 Subprocess Management

Each Copilot CLI invocation is managed as:
```python
process = subprocess.Popen(
    cmd,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    cwd=project_path,
    env=env,
)
```

- stdout and stderr are captured in real-time via non-blocking reads and written to the phase log file.
- The worker maintains an in-memory registry of active subprocesses keyed by `(workflow_run_id, phase_id)`.
- On cancel: `process.kill()` is called immediately.

### 11.3 Monitoring Data (Per Phase Attempt)

| Field | Description |
|-------|-------------|
| `pid` | OS process ID of the Copilot CLI subprocess |
| `status` | Current phase status |
| `started_at` | Timestamp when subprocess was launched |
| `ended_at` | Timestamp when subprocess exited |
| `exit_code` | Subprocess exit code (null if still running) |
| `branch` | Git branch name (null if not a git repo) |
| `repo_path` | Absolute path to the project folder |
| `retry_count` | Number of retries attempted so far |
| `log_file` | Path to the log file for this attempt |

### 11.4 Ghost/Lost Process Detection

The worker implements a heartbeat-based ghost detection:
1. Every 10 seconds, the worker checks all in-memory tracked PIDs against the OS process table.
2. If a tracked PID no longer exists but the phase is still marked `running`:
   - Mark the phase as failed with reason `process_lost`.
   - Trigger retry logic.
3. On worker startup, the worker scans for any phases marked `running` or `starting` in the database:
   - Check if the PID is still alive.
   - If alive, re-adopt the process (re-attach stdout/stderr monitoring).
   - If dead, mark as failed with reason `process_lost_worker_restart` and trigger retry.

**Assumption:** Re-adopting a subprocess after worker restart means the worker loses the stdout/stderr pipes. The worker will note this in the logs and start a new log file segment. Historical log data from before the restart is preserved in the existing log file. Re-adoption monitors only PID liveness, not output, until the subprocess exits. This is acceptable for v1.

### 11.5 Concurrency Scheduling

- The worker determines max concurrent workflows based on system resources.
- Heuristic: `max(1, min(cpu_count / 2, available_ram_gb / 4))`, clamped to [1, 8].
- When a new workflow is queued and concurrency limit is reached, it remains in `queued` status.
- The worker picks up queued workflows in FIFO order when a slot opens.

---

## 12. Persistence Model

### 12.1 Database Schema

All timestamps are stored as ISO 8601 UTC strings.

#### `projects`
| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | UUID |
| `name` | TEXT | Display name (derived from folder name, editable) |
| `path` | TEXT UNIQUE | Absolute path to the project folder |
| `is_git_repo` | BOOLEAN | Whether the path is a git repository |
| `created_at` | TEXT | Creation timestamp |
| `updated_at` | TEXT | Last update timestamp |

#### `project_settings`
| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | UUID |
| `project_id` | TEXT FK | References projects.id |
| `phase_model_mapping` | TEXT | JSON: phase name -> model identifier |
| `retry_count` | INTEGER NULL | Override for max retries |
| `review_fix_loop_limit` | INTEGER NULL | Override for max review-fix loops |
| `autopilot_default` | BOOLEAN NULL | Override for autopilot default |

#### `workflow_runs`
| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | UUID (this is the run ID) |
| `project_id` | TEXT FK | References projects.id |
| `name` | TEXT | User-provided workflow name |
| `status` | TEXT | Workflow status enum |
| `branch` | TEXT NULL | Git branch name (null if not git) |
| `autopilot` | BOOLEAN | Whether autopilot is enabled for this run |
| `review_fix_loop_count` | INTEGER | Current review-fix iteration count |
| `review_fix_loop_limit` | INTEGER | Max review-fix iterations for this run |
| `retry_limit` | INTEGER | Max retries per phase for this run |
| `phase_model_mapping` | TEXT | JSON: phase name -> model (resolved from global/project/run) |
| `context_paths` | TEXT | JSON array of selected file/folder paths |
| `created_at` | TEXT | |
| `updated_at` | TEXT | |

#### `phases`
| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | UUID |
| `workflow_run_id` | TEXT FK | References workflow_runs.id |
| `phase_type` | TEXT | Enum: exploration, planning, plan_critique, plan_correction, execution, review |
| `sequence_number` | INTEGER | Order in workflow (0-5) |
| `status` | TEXT | Phase status enum |
| `current_attempt` | INTEGER | Latest attempt number |
| `created_at` | TEXT | |
| `updated_at` | TEXT | |

#### `phase_attempts`
| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | UUID |
| `phase_id` | TEXT FK | References phases.id |
| `attempt_number` | INTEGER | Sequential attempt number |
| `status` | TEXT | Attempt status (running, succeeded, failed, cancelled) |
| `pid` | INTEGER NULL | OS process ID |
| `exit_code` | INTEGER NULL | Subprocess exit code |
| `started_at` | TEXT NULL | |
| `ended_at` | TEXT NULL | |
| `error_message` | TEXT NULL | Error details if failed |
| `log_file_path` | TEXT | Path to log file |
| `rendered_prompt` | TEXT | The exact prompt sent to Copilot CLI |

#### `exploration_messages`
| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | UUID |
| `workflow_run_id` | TEXT FK | References workflow_runs.id |
| `role` | TEXT | 'user' or 'assistant' |
| `content` | TEXT | Message content (Markdown) |
| `sequence_number` | INTEGER | Message order |
| `created_at` | TEXT | |

#### `review_comments`
| Column | Type | Description |
|--------|------|-------------|
| `id` | TEXT PK | UUID |
| `phase_attempt_id` | TEXT FK | References phase_attempts.id |
| `file_path` | TEXT NULL | Relative file path (null if not file-specific) |
| `line_number` | INTEGER NULL | Line number (null if not line-specific) |
| `severity` | TEXT | error, warning, suggestion |
| `comment` | TEXT | Comment text |

#### `user_settings`
| Column | Type | Description |
|--------|------|-------------|
| `key` | TEXT PK | Setting key |
| `value` | TEXT | JSON-encoded value |
| `updated_at` | TEXT | |

### 12.2 Migrations

- Migrations are managed via Alembic.
- Auto-applied on server startup.
- Migration files are bundled in the Docker image.

---

## 13. Artifact Layout

### 13.1 Repo Artifacts (in project folder)

```
.relay/
  <run-id>/
    exploration/
      planning_prompt.md           # Generated planning prompt
      messages/
        001_user.json              # Structured message file
        002_assistant.json
        ...
      transcript.md                # Rendered full chat transcript
    planning/
      SPEC.md                      # Latest spec
      IMPLEMENTATION_PLAN.md       # Latest plan (overwritten by correction)
    critique/
      IMPLEMENTATION_PLAN_CRITIQUED.md
    execution/
      # No explicit artifacts; changes are in working tree
    review/
      REVIEW_COMMENTS.json         # Latest review comments
      REVIEW_SUMMARY.md            # Latest review summary
    attempts/
      planning_attempt_1/
        SPEC.md
        IMPLEMENTATION_PLAN.md
      planning_attempt_2/
        SPEC.md
        IMPLEMENTATION_PLAN.md
      critique_attempt_1/
        IMPLEMENTATION_PLAN_CRITIQUED.md
      plan_correction_attempt_1/
        IMPLEMENTATION_PLAN.md     # Pre-correction version preserved
      review_attempt_1/
        REVIEW_COMMENTS.json
        REVIEW_SUMMARY.md
      review_attempt_2/
        REVIEW_COMMENTS.json
        REVIEW_SUMMARY.md
```

### 13.2 Message File Format

```json
{
  "id": "uuid",
  "role": "user",
  "content": "message text...",
  "timestamp": "2026-03-28T12:00:00Z",
  "sequence": 1
}
```

### 13.3 Log Files (app-level storage)

```
<relay-data-dir>/
  logs/
    <run-id>/
      exploration_attempt_1.log
      planning_attempt_1.log
      planning_attempt_2.log       # retry
      critique_attempt_1.log
      correction_attempt_1.log
      execution_attempt_1.log
      execution_attempt_2.log      # fix loop iteration
      review_attempt_1.log
      review_attempt_2.log         # fix loop iteration
```

`<relay-data-dir>` defaults to `~/.relay` or is configurable via `RELAY_DATA_DIR` env var. In Docker, this is a mounted volume.

---

## 14. API Surface

### 14.1 REST Endpoints

All endpoints are prefixed with `/api/v1`.

#### System
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Health check (DB connectivity, worker status, Copilot CLI availability) |
| `GET` | `/system/status` | System info: version, copilot status, worker status, concurrency info |

#### Projects
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/projects` | List all projects |
| `POST` | `/projects` | Add a project (body: `{path, name?}`) |
| `GET` | `/projects/{id}` | Get project details |
| `PUT` | `/projects/{id}` | Update project (name, settings) |
| `DELETE` | `/projects/{id}` | Remove project (does not delete files) |
| `GET` | `/projects/{id}/files` | Browse project file tree (for context selection) |
| `GET` | `/projects/{id}/settings` | Get project-level settings |
| `PUT` | `/projects/{id}/settings` | Update project-level settings |

#### Workflow Runs
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/runs` | List all runs (query params: `project_id`, `status`, `limit`, `offset`) |
| `POST` | `/runs` | Create a new workflow run |
| `GET` | `/runs/{id}` | Get run details (includes phases) |
| `DELETE` | `/runs/{id}` | Delete a run (only if not running) |

#### Phases
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/runs/{run_id}/phases` | List phases for a run |
| `GET` | `/runs/{run_id}/phases/{phase_id}` | Get phase details (includes attempts) |
| `GET` | `/runs/{run_id}/phases/{phase_id}/attempts/{attempt_number}` | Get attempt details |
| `GET` | `/runs/{run_id}/phases/{phase_id}/attempts/{attempt_number}/logs` | Get logs (query: `offset` for pagination) |
| `GET` | `/runs/{run_id}/phases/{phase_id}/prompt` | Get the rendered prompt for the latest attempt |

#### Exploration
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/runs/{run_id}/exploration/messages` | Send a chat message |
| `GET` | `/runs/{run_id}/exploration/messages` | Get all messages |
| `POST` | `/runs/{run_id}/exploration/finalize` | Finalize exploration |
| `PUT` | `/runs/{run_id}/exploration/context` | Update context path selections |
| `GET` | `/runs/{run_id}/exploration/context` | Get current context selections |

#### Workflow Control
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/runs/{run_id}/advance` | Advance to next phase (non-autopilot pause points) |
| `POST` | `/runs/{run_id}/cancel` | Cancel the workflow |
| `POST` | `/runs/{run_id}/rerun` | Rerun from a phase (body: `{from_phase_type}`) |
| `POST` | `/runs/{run_id}/review/approve` | Approve review and complete workflow |
| `POST` | `/runs/{run_id}/review/fix` | Send findings back to execution (body: `{fix_prompt?}`) |

#### Artifacts
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/runs/{run_id}/artifacts/{path}` | Get artifact content by path |

#### Settings
| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/settings` | Get all user settings |
| `PUT` | `/settings` | Update user settings |

### 14.2 Request/Response Patterns

**Create Run Request:**
```json
{
  "project_id": "uuid",
  "name": "Add user auth feature",
  "phase_model_mapping": {
    "exploration": "gpt-4o",
    "planning": "claude-sonnet-4-6",
    "plan_critique": "claude-sonnet-4-6",
    "plan_correction": "claude-sonnet-4-6",
    "execution": "claude-sonnet-4-6",
    "review": "claude-sonnet-4-6"
  },
  "retry_limit": 5,
  "review_fix_loop_limit": 5,
  "autopilot": true
}
```
All fields except `project_id` and `name` are optional and fall back to project then global defaults.

**Run Detail Response:**
```json
{
  "id": "uuid",
  "project_id": "uuid",
  "project_name": "my-project",
  "name": "Add user auth feature",
  "status": "running",
  "branch": "relay/abc-123",
  "autopilot": true,
  "review_fix_loop_count": 1,
  "review_fix_loop_limit": 5,
  "phases": [
    {
      "id": "uuid",
      "phase_type": "exploration",
      "sequence_number": 0,
      "status": "succeeded",
      "current_attempt": 1,
      "latest_attempt": {
        "attempt_number": 1,
        "status": "succeeded",
        "started_at": "...",
        "ended_at": "..."
      }
    },
    ...
  ],
  "context_paths": ["/src", "/tests/test_main.py"],
  "created_at": "...",
  "updated_at": "..."
}
```

---

## 15. WebSocket Event Model

### 15.1 Connection

- Endpoint: `ws://host:port/api/v1/ws`
- After connection, client sends subscription messages to register interest in specific runs.
- Client can subscribe to multiple runs simultaneously.

### 15.2 Client -> Server Messages

```json
{"type": "subscribe", "run_id": "uuid"}
{"type": "unsubscribe", "run_id": "uuid"}
{"type": "subscribe_all"}
```

`subscribe_all` receives status updates for all runs (used by the Runs list page).

### 15.3 Server -> Client Messages

#### Workflow Status Change
```json
{
  "type": "workflow_status",
  "run_id": "uuid",
  "status": "running",
  "timestamp": "..."
}
```

#### Phase Status Change
```json
{
  "type": "phase_status",
  "run_id": "uuid",
  "phase_id": "uuid",
  "phase_type": "planning",
  "status": "running",
  "attempt_number": 1,
  "timestamp": "..."
}
```

#### Log Line
```json
{
  "type": "log",
  "run_id": "uuid",
  "phase_id": "uuid",
  "attempt_number": 1,
  "stream": "stdout",
  "line": "Generating implementation plan...\n",
  "timestamp": "..."
}
```

#### Exploration Response Chunk (Streaming)
```json
{
  "type": "exploration_chunk",
  "run_id": "uuid",
  "message_id": "uuid",
  "content": "partial text...",
  "done": false
}
```

When streaming is complete:
```json
{
  "type": "exploration_chunk",
  "run_id": "uuid",
  "message_id": "uuid",
  "content": "",
  "done": true
}
```

#### Exploration Finalized
```json
{
  "type": "exploration_finalized",
  "run_id": "uuid",
  "planning_prompt_preview": "First 500 chars of the planning prompt..."
}
```

#### Review Results Available
```json
{
  "type": "review_results",
  "run_id": "uuid",
  "phase_id": "uuid",
  "attempt_number": 1,
  "verdict": "FAIL",
  "comment_count": 12,
  "summary_preview": "First 500 chars of review summary..."
}
```

#### Error
```json
{
  "type": "error",
  "run_id": "uuid",
  "message": "Copilot CLI process exited with code 1",
  "phase_type": "execution",
  "timestamp": "..."
}
```

---

## 16. UI Structure

### 16.1 Layout

**Global Elements:**
- Top navbar with:
  - App logo / name ("Relay")
  - Navigation: Projects, Runs, Settings
  - Autopilot toggle switch (always visible, persisted to settings)
  - Copilot CLI status indicator (green/red dot)

### 16.2 Pages

#### Projects List (`/projects`)
- Card or table listing all projects
- Each shows: name, path, git status, active run count
- "Add Project" button

#### Project Detail (`/projects/:id`)
- Tabs: Overview | Runs | Configuration
- **Overview tab:**
  - Project info (name, path, is_git_repo, git branch/status)
  - Active runs summary (count + status badges)
  - "New Workflow" button (prominent, primary action)
- **Runs tab:**
  - Table of runs for this project, newest first
  - Columns: name, status, created date, duration
  - Click to navigate to run detail
- **Configuration tab:**
  - Phase-to-model mapping overrides (table of phase -> model dropdown)
  - Retry count override
  - Review-fix loop limit override
  - Autopilot default override
  - Each field has a "Use global default" / "Override" toggle

#### New Workflow Form (`/projects/:id/workflows/new`)
- Required: workflow name (text input)
- Project is pre-selected from navigation context
- **Default section (always visible):**
  - Workflow name
- **Advanced section (collapsed by default):**
  - Phase model mapping overrides
  - Retry count
  - Review-fix loop limit
  - Autopilot override
- "Create & Start" button

#### Run Detail (`/runs/:id`) — Primary Workflow View
- **Left/Main Area: Phase Graph**
  - Vertical list of phases (GitHub Actions-style)
  - Each phase node shows:
    - Phase name
    - Status icon/badge (color-coded)
    - Duration (if completed)
    - Attempt count (if > 1)
  - Active phase has a pulsing/animated indicator
  - Clicking a phase selects it and populates the detail panel
  - Lines/connectors between phases show flow
  - Review-fix loop is visually indicated (arc/arrow from Review back to Execution with loop counter)

- **Right Area: Phase Detail Panel**
  - Default: shows workflow summary (name, status, branch, timing, context paths)
  - When a phase is selected:
    - **Header:** Phase name, status, timing
    - **Tabs:**
      - **Summary:** Phase outcome summary, key artifacts preview
      - **Prompt:** Exact rendered prompt sent to Copilot CLI (read-only, syntax-highlighted Markdown)
      - **Logs:** Live-streaming or persisted logs (monospace, auto-scroll with scroll-lock)
      - **Review Comments:** (Review phase only) Structured comments table with file, line, severity, message
      - **Attempts:** Attempt history list with status, timing, link to view each attempt's logs/prompt

  - **Exploration Phase (special rendering):**
    - The main area becomes a chat interface instead of the graph
    - Chat messages with user/assistant bubbles
    - Input box at bottom (disabled after finalization)
    - Finalize button
    - Context panel slides in from the right showing file tree with checkboxes
    - After finalization: planning prompt rendered read-only
    - Graph remains visible as a compact sidebar/breadcrumb

#### Runs List (`/runs`)
- Table of all runs across all projects, newest first
- Columns: project name, workflow name, status, created date, duration
- Filters: project dropdown, status multi-select
- Click to navigate to run detail

#### Settings (`/settings`)
- **General:**
  - Relay data directory (display only; configured via env var)
  - Copilot CLI path override (default: auto-detect)
- **Models:**
  - Global default phase-to-model mapping
  - Table: phase name | model identifier (text input or dropdown if model list is known)
- **Autopilot:**
  - Default autopilot on/off
- **Retry/Loop Limits:**
  - Default max retries per phase
  - Default max review-fix loop iterations

### 16.3 Visual Design Direction

- Clean, professional, minimal aesthetic inspired by GitHub's design language
- Dark and light mode support (follows system preference, toggleable)
- Color-coded status indicators:
  - Queued: gray
  - Running: blue (animated)
  - Succeeded: green
  - Failed: red
  - Cancelled: orange
  - Stale: faded/dimmed
  - Waiting for user: yellow/amber
  - Completed with unresolved findings: green with warning badge
- Monospace font for logs and prompts
- Syntax highlighting for Markdown artifact previews

---

## 17. Settings and Configuration Model

### 17.1 Configuration Precedence (Highest to Lowest)

1. Per-run override (from New Workflow form)
2. Project-level override
3. Global user settings
4. Application defaults

### 17.2 Application Defaults

| Setting | Default |
|---------|---------|
| `phase_model_mapping.exploration` | `""` (empty = use Copilot default) |
| `phase_model_mapping.planning` | `""` |
| `phase_model_mapping.plan_critique` | `""` |
| `phase_model_mapping.plan_correction` | `""` |
| `phase_model_mapping.execution` | `""` |
| `phase_model_mapping.review` | `""` |
| `retry_limit` | `5` |
| `review_fix_loop_limit` | `5` |
| `autopilot` | `true` |

**Assumption:** An empty string for model means "use whatever Copilot CLI's default model is." The app passes no model flag to Copilot CLI in this case.

The app ships with a hardcoded list of known Copilot-supported models. The UI presents this list as a dropdown for model selection per phase. The list is maintained in the app codebase and updated with new releases.

### 17.3 Setting Storage

- User settings are stored in the `user_settings` SQLite table.
- Project settings are stored in the `project_settings` table.
- Run settings are denormalized into the `workflow_runs` row at creation time (resolved from precedence chain).
- Once a run is created, its settings are immutable.

---

## 18. Copilot CLI Integration Contract

### 18.1 Prerequisites

- GitHub Copilot CLI (`gh` + Copilot extension) is pre-installed in the Docker image.
- The user must volume-mount their `gh` auth credentials (typically `~/.config/gh/`) into the container.
- Relay does NOT auto-authenticate Copilot CLI. If auth is missing, the app shows a banner with instructions.

### 18.2 Detection

On server startup and on-demand via the health endpoint:
1. Check if `gh` is in PATH.
2. Run `gh copilot --version` (or equivalent) to verify Copilot extension is installed.
3. Run `gh auth status` to check authentication.
4. Report status to the UI (banner if not available).

**Assumption:** The exact Copilot CLI commands may differ based on the version. The app stores the detected Copilot CLI command template in a config constant that can be updated without code changes. For v1, we target `gh copilot` as the CLI interface.

### 18.3 Invocation Patterns

#### Ask Mode (Exploration only)
```bash
gh copilot suggest --type chat \
  --model <model> \
  --cwd <project_path>
```

**Assumption:** The exact Ask-mode invocation depends on Copilot CLI's interface. If Copilot CLI supports a stdin/stdout interactive mode, the app uses that. If it only supports one-shot queries, the app sends one message at a time and accumulates context in the prompt. The app wraps this behind an internal `CopilotSession` abstraction that handles the specifics.

#### Agent Mode (All other phases)
```bash
gh copilot agent \
  --model <model> \
  --cwd <project_path> \
  --prompt <prompt_text_or_file>
```

**Assumption:** Same caveat as above regarding exact CLI flags. The app's `CopilotSession` abstraction normalizes this.

### 18.4 Session Lifecycle

A "session" corresponds to a single Copilot CLI subprocess:

1. **Start:** `subprocess.Popen(cmd, ...)` with project directory as cwd.
2. **Interact:** Write to stdin, read from stdout/stderr.
3. **End:** The subprocess exits naturally when the task is complete, or is killed on cancellation.

For phases that "reuse" a session (Plan Correction reusing Planning, Execution fix loop):
- The subprocess is kept alive between phases.
- New prompts are sent to the existing subprocess's stdin.
- If the subprocess has exited, a new one is started (degraded mode).

### 18.5 Prompt Construction

The app constructs prompts for each phase. Prompts include:

1. **System context:** Phase instructions, output format requirements.
2. **Artifacts:** Relevant prior artifacts (planning prompt, SPEC.md, IMPLEMENTATION_PLAN.md, etc.).
3. **Context paths:** The selected file/folder paths from Exploration.
4. **Model-specific instructions:** (if any) based on the model being used.

Prompt templates are stored as Python string templates in the app codebase. They are not user-editable in v1.

### 18.6 Model Passing

- If a model is configured for a phase, pass it via the `--model` flag.
- If no model is configured (empty string), omit the `--model` flag entirely.
- The app does NOT validate model identifiers. If the model is invalid, the Copilot CLI will error and the standard retry logic applies.

### 18.7 AGENTS.md / Copilot Instructions

- The app does NOT create, modify, or inject `AGENTS.md` or `.github/copilot-instructions.md`.
- If these files exist in the project, Copilot CLI will discover and use them per its own behavior.
- The app's phase prompts are designed to be self-contained and do not depend on these files existing.

---

## 19. Projects and Runs

### 19.1 Adding a Project

1. User provides an absolute local folder path.
2. App validates:
   - Path exists and is a directory.
   - Path is readable by the app process.
3. App detects:
   - Whether it is a git repository (checks for `.git` directory or `git rev-parse`).
4. App stores the project in the database.
5. New project inherits global default settings.

**Assumption:** Project names default to the last segment of the path (e.g., `/home/user/my-project` -> `my-project`). User can rename.

### 19.2 Git Branch Strategy

For git repos:
1. When a workflow run is created, the app records the current HEAD commit hash.
2. When Execution phase starts, the worker creates a branch: `relay/<run-id>` from that commit.
3. All Execution and Review work happens on this branch.
4. The branch is never automatically merged or deleted.
5. User manages branch cleanup externally.

**Assumption:** The branch is created just before Execution, not at workflow creation. This means Exploration, Planning, Critique, and Correction phases run against whatever branch is currently checked out (typically `main`). This is intentional: those phases are read-only and don't modify files.

### 19.3 Non-Git Projects

- Changes are made directly in the project folder.
- Concurrent workflows on the same non-git folder are allowed but a warning is shown:
  > "Warning: Multiple workflows are active on this project folder. Since this is not a git repository, concurrent workflows may produce conflicting file changes."
- The warning is shown on the project page and on each run detail page.

### 19.4 Run Lifecycle

1. **Created:** Run row inserted, phases pre-created with `queued` status.
2. **Queued:** Waiting for worker capacity.
3. **Running:** Worker picks up the run. Exploration phase starts.
4. **Phase progression:** Each phase completes and the next begins (auto or manual).
5. **Terminal state:** One of `completed`, `completed_with_unresolved_findings`, `failed`, `cancelled`.

---

## 20. Concurrency Model

### 20.1 Global Concurrency

- Determined automatically by the worker on startup using system resource heuristics.
- Formula: `max(1, min(cpu_count // 2, available_ram_gb // 4))`, clamped to [1, 8].
- Displayed in the system status endpoint and UI.
- Not user-configurable in v1.

### 20.2 Per-Workflow

- One active phase at a time per workflow.
- The worker never runs two phases from the same workflow concurrently.

### 20.3 Queue Behavior

- When concurrency slots are full, new workflows wait in `queued` status.
- FIFO ordering.
- Workflows are picked up as slots become available.

---

## 21. Edge-Case Decisions

### 21.1 Exploration Chat — Long Conversations

If an Exploration chat grows very long and approaches Copilot CLI context limits:
- The app does NOT truncate or summarize. The user should finalize and start a new workflow if needed.
- **Rationale:** Exploration is interactive and user-controlled; forcing summarization mid-conversation would be disruptive.

### 21.2 Artifacts Missing After Phase

If a phase completes (exit code 0) but expected artifacts are missing:
- The phase is marked as `failed` with reason `artifacts_missing`.
- Standard retry logic applies.
- This handles cases where the model completed without producing required outputs.

### 21.3 Concurrent Runs on Same Git Repo

- Each run gets its own branch. They can operate concurrently on different branches without conflict.
- However, branch creation happens at Execution start. If two runs reach Execution simultaneously, both branch from the same HEAD, so their changes will diverge.
- The app does NOT attempt to merge branches or detect conflicts between concurrent runs.

### 21.4 Project Path Becomes Invalid

If a project path is deleted or becomes inaccessible:
- Existing runs can still be viewed (data is in DB and app logs).
- New workflows on that project will fail at first phase start.
- The project page shows a warning: "Project path is no longer accessible."
- The app re-validates project path on project detail page load (not on every run list load, to avoid performance issues).

### 21.5 Worker Crash During Active Runs

- On worker restart, the ghost/lost process detection (Section 11.4) handles in-flight runs.
- Runs with lost processes are retried automatically.
- No manual intervention needed in most cases.

### 21.6 SQLite Concurrent Access

- SQLite supports multiple readers but only one writer at a time.
- The server (API) and worker both access the same SQLite file.
- Write contention is managed via SQLite's built-in WAL mode and busy timeout (5 seconds).
- For v1 traffic levels (single user, low write frequency), this is sufficient.
- The database file is created in `<relay-data-dir>/relay.db`.

### 21.7 Exploration Finalization Fails

If the planning prompt generation message (sent during finalization) fails:
- Standard retry logic applies to the generation.
- If retries are exhausted, the Exploration phase is marked failed.
- The user can rerun Exploration (which creates a new chat — the old messages are preserved in attempt history but the new attempt starts a fresh conversation).

**Assumption:** This is an acceptable UX tradeoff. The alternative (letting users append to the same chat after a failure) would complicate state management. Since the conversation transcript is preserved, the user can reference it when starting the new attempt.

### 21.8 Disk Space for Logs/Artifacts

- The app does NOT monitor disk space.
- If disk space runs out, phases will fail with IO errors and retry (which will also fail).
- Users are responsible for managing disk space.
- Future versions may add a cleanup/retention policy.

### 21.9 Very Large Log Output

- Log files are unbounded in v1.
- The UI log viewer paginates (loads latest N lines, scroll up to load more).
- Log streaming via WebSocket sends lines as they arrive; no batching or throttling in v1.

**Assumption:** For v1, unbounded logs are acceptable. If this becomes a problem, a future version can add log rotation or streaming backpressure.

### 21.10 Copilot CLI Version Changes

- The app does not pin or check Copilot CLI versions beyond basic detection.
- If a Copilot CLI update changes the interface, prompts, or behavior, the app may break.
- The `CopilotSession` abstraction centralizes the interface to minimize blast radius.

### 21.11 Multiple Relay Instances on Same Machine

- Not supported. The SQLite database and data directory assume single-instance access.
- Running multiple instances would cause database corruption.
- No explicit locking or detection in v1.

### 21.12 Fix Prompt Editing in Non-Autopilot

- The editable fix prompt is pre-populated with the app's default fix prompt (containing review findings, spec, and plan references).
- The user can freely edit this before sending.
- The edited prompt is stored in the phase attempt record for auditability.
- There is no "reset to default" button; the user can cancel and click "Send to Fix" again to get a fresh default prompt.

---

## 22. Assumptions

This section collects all assumptions made throughout the spec for easy reference.

1. **Session reuse degradation:** If a reused subprocess has exited, a new one is started with accumulated context in the prompt. Conversation history is NOT replayed.

2. **Critique delimiter format:** `<!-- CRITIQUE: ... -->` for machine parsing, `> **Critique:** ...` for human display.

3. **Review parsing:** Review output is parsed from Copilot CLI stdout using sentinel-fenced code blocks. Parsing failure falls back to raw capture.

4. **Waiting for user status:** Added `waiting_for_user` to both workflow and phase status enums to distinguish paused workflows.

5. **Cancellation + rerun:** Rerun after cancellation follows the same mechanics as rerun after failure.

6. **Log streaming:** Via filesystem tailing, not database writes.

7. **Branch timing:** Git branches are created at Execution start, not workflow creation.

8. **Project naming:** Defaults to last path segment.

9. **Model empty string:** Means "use Copilot CLI default."

10. **Exploration rerun:** Starts a fresh conversation (old messages preserved in attempt history).

11. **Copilot CLI command format:** Wrapped behind a `CopilotSession` abstraction; exact flags may vary and are centralized.

12. **Worker re-adoption:** After restart, the worker can re-adopt live PIDs but loses stdout/stderr pipes.

13. **Single instance:** Only one Relay instance should access a given data directory.

14. **Planning prompt generation:** Final message to the Exploration Copilot session, using a structured template the model fills in.

---

## 23. Glossary

| Term | Definition |
|------|-----------|
| **Workflow** | A complete orchestrated sequence of phases for a given task |
| **Run** | A specific execution of a workflow; identified by a run ID |
| **Phase** | A single step in the workflow (Exploration, Planning, etc.) |
| **Attempt** | A single execution attempt of a phase (includes retries and reruns) |
| **Autopilot** | Mode where phases advance automatically without user approval |
| **Review-fix loop** | The cycle of Review finding issues and Execution fixing them |
| **Session** | A single Copilot CLI subprocess; may span multiple phases if reused |
| **Artifact** | A file produced by a phase (SPEC.md, IMPLEMENTATION_PLAN.md, etc.) |
| **Context paths** | File/folder paths selected during Exploration and passed to all phases |
| **Ask mode** | Copilot CLI read-only/conversational mode (Exploration only) |
| **Agent mode** | Copilot CLI autonomous mode that can modify files (all non-Exploration phases) |
| **Ghost process** | A subprocess that the worker has lost track of |
| **Stale** | A phase result invalidated by rerunning a predecessor phase |
