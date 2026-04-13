# Relay v1 Implementation Plan

---

## Risk Map

These are the areas most likely to cause rework or block progress. They are addressed early in the build order.

| Risk | Why It's Risky | Mitigation |
|------|---------------|------------|
| **Copilot CLI subprocess I/O** | Copilot CLI's stdin/stdout/stderr behavior is under-documented. Streaming, interactive mode support, and session reuse all depend on it. | Build CopilotSession abstraction in Phase 1. Test with real CLI immediately. Build a mock/fake session for all other development. |
| **Session reuse (Planning→Correction, Execution fix loop)** | Keeping a subprocess alive across phases and writing follow-up prompts to stdin may not work cleanly. | Validate in Phase 1. If stdin follow-up fails, fall back to "new session with full context replay" as the primary mode. |
| **Log streaming at scale** | File tailing + WebSocket fan-out under concurrent workflows could lag or drop lines. | Keep it simple: one tail coroutine per active subscription. No batching in v1. Load-test in Phase 5. |
| **SQLite WAL contention** | Server and worker both write. Under concurrent workflows, busy timeouts could stall the worker. | Set WAL mode + 5s busy timeout from day one. Monitor in integration tests. |
| **Review output parsing** | Model output is non-deterministic. Parsing REVIEW_COMMENTS.json and verdict from stdout may fail. | Always save raw output. Parsing is best-effort with fallback to REVIEW_RAW.md. Test with diverse model outputs. |
| **Exploration streaming UX** | Chat streaming must feel responsive. WebSocket chunk delivery, partial message rendering, and send-button locking all need to be tight. | Build Exploration UI with a hardcoded mock backend first (Phase 4), then wire to real backend. |

---

## Project Structure

```
relay/
├── pyproject.toml                  # uv project, all Python deps
├── alembic.ini
├── alembic/
│   └── versions/
├── Dockerfile
├── docker-compose.yml              # dev: server + worker + volume mounts
├── relay/
│   ├── __init__.py
│   ├── cli.py                      # Entry point: relay serve | worker | dev
│   ├── config.py                   # Settings, env vars, defaults
│   ├── models/                     # SQLAlchemy ORM models
│   │   ├── __init__.py
│   │   ├── project.py
│   │   ├── workflow_run.py
│   │   ├── phase.py
│   │   ├── phase_attempt.py
│   │   ├── exploration_message.py
│   │   ├── review_comment.py
│   │   └── user_setting.py
│   ├── db.py                       # Engine, session factory, WAL setup
│   ├── schemas/                    # Pydantic request/response schemas
│   │   ├── __init__.py
│   │   ├── project.py
│   │   ├── run.py
│   │   ├── phase.py
│   │   ├── exploration.py
│   │   ├── settings.py
│   │   └── ws.py
│   ├── api/                        # FastAPI routers
│   │   ├── __init__.py
│   │   ├── app.py                  # FastAPI app factory
│   │   ├── system.py               # /health, /system/status
│   │   ├── projects.py
│   │   ├── runs.py
│   │   ├── phases.py
│   │   ├── exploration.py
│   │   ├── workflow_control.py     # advance, cancel, rerun, approve, fix
│   │   ├── artifacts.py
│   │   ├── settings.py
│   │   └── ws.py                   # WebSocket endpoint + subscription manager
│   ├── worker/
│   │   ├── __init__.py
│   │   ├── main.py                 # Worker main loop (poll + dispatch)
│   │   ├── scheduler.py            # Concurrency heuristics, queue management
│   │   ├── orchestrator.py         # Phase sequencing, state machine transitions
│   │   ├── phase_runner.py         # Run a single phase (subprocess lifecycle)
│   │   ├── retry.py                # Backoff logic, retry counting
│   │   ├── process_monitor.py      # Ghost detection, PID health checks
│   │   └── git_ops.py              # Branch creation, git detection
│   ├── copilot/
│   │   ├── __init__.py
│   │   ├── session.py              # CopilotSession: Popen wrapper, stdin/stdout I/O
│   │   ├── detection.py            # gh/copilot/auth availability checks
│   │   └── prompts.py              # All phase prompt templates
│   ├── artifacts/
│   │   ├── __init__.py
│   │   ├── manager.py              # Create dirs, write/read artifacts, copy to attempt folders
│   │   ├── parsers.py              # Review output parsing (JSON, verdict, fallback)
│   │   └── exploration.py          # Message file I/O, transcript generation
│   ├── realtime/
│   │   ├── __init__.py
│   │   ├── log_tailer.py           # Async file tail for log streaming
│   │   ├── notifier.py             # DB poll → WebSocket broadcast bridge
│   │   └── connection_manager.py   # WebSocket connection + subscription registry
│   └── services/
│       ├── __init__.py
│       ├── project_service.py      # Project CRUD + validation
│       ├── run_service.py          # Run creation, settings resolution
│       ├── phase_service.py        # Phase/attempt queries
│       └── settings_service.py     # Settings read/write with precedence
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── index.html
│   ├── src/
│   │   ├── main.tsx
│   │   ├── App.tsx
│   │   ├── api/
│   │   │   ├── client.ts           # Fetch wrapper, base URL
│   │   │   ├── projects.ts
│   │   │   ├── runs.ts
│   │   │   ├── phases.ts
│   │   │   ├── exploration.ts
│   │   │   ├── settings.ts
│   │   │   └── ws.ts               # WebSocket client, subscription hooks
│   │   ├── hooks/
│   │   │   ├── useWebSocket.ts
│   │   │   ├── useRunStatus.ts
│   │   │   ├── useLogStream.ts
│   │   │   └── useExplorationChat.ts
│   │   ├── pages/
│   │   │   ├── ProjectsListPage.tsx
│   │   │   ├── ProjectDetailPage.tsx
│   │   │   ├── NewWorkflowPage.tsx
│   │   │   ├── RunDetailPage.tsx
│   │   │   ├── RunsListPage.tsx
│   │   │   └── SettingsPage.tsx
│   │   ├── components/
│   │   │   ├── layout/
│   │   │   │   ├── Navbar.tsx
│   │   │   │   ├── AppShell.tsx
│   │   │   │   └── AutopilotToggle.tsx
│   │   │   ├── workflow/
│   │   │   │   ├── PhaseGraph.tsx
│   │   │   │   ├── PhaseNode.tsx
│   │   │   │   ├── ReviewFixLoopIndicator.tsx
│   │   │   │   └── WorkflowStatusBadge.tsx
│   │   │   ├── detail-panel/
│   │   │   │   ├── PhaseDetailPanel.tsx
│   │   │   │   ├── PhaseSummaryTab.tsx
│   │   │   │   ├── PhasePromptTab.tsx
│   │   │   │   ├── PhaseLogsTab.tsx
│   │   │   │   ├── ReviewCommentsTab.tsx
│   │   │   │   ├── AttemptHistoryTab.tsx
│   │   │   │   └── WorkflowSummary.tsx
│   │   │   ├── exploration/
│   │   │   │   ├── ChatThread.tsx
│   │   │   │   ├── ChatInput.tsx
│   │   │   │   ├── ContextPanel.tsx
│   │   │   │   ├── FileTreeBrowser.tsx
│   │   │   │   ├── PlanningPromptView.tsx
│   │   │   │   └── FinalizeButton.tsx
│   │   │   ├── review/
│   │   │   │   ├── ReviewApprovalBar.tsx
│   │   │   │   └── FixPromptEditor.tsx
│   │   │   └── shared/
│   │   │       ├── StatusBadge.tsx
│   │   │       ├── LogViewer.tsx
│   │   │       ├── MarkdownRenderer.tsx
│   │   │       └── ConfirmDialog.tsx
│   │   ├── store/                  # Zustand or similar lightweight state
│   │   │   ├── index.ts
│   │   │   ├── runStore.ts
│   │   │   └── settingsStore.ts
│   │   └── types/
│   │       ├── api.ts              # TypeScript types matching Pydantic schemas
│   │       └── ws.ts               # WebSocket message types
│   └── public/
└── tests/
    ├── conftest.py
    ├── factories.py                # Test data factories
    ├── mocks/
    │   └── fake_copilot.py         # Fake CopilotSession for testing
    ├── unit/
    │   ├── test_state_machine.py
    │   ├── test_retry.py
    │   ├── test_scheduler.py
    │   ├── test_prompt_builder.py
    │   ├── test_artifact_parser.py
    │   ├── test_settings_resolution.py
    │   └── test_git_ops.py
    ├── integration/
    │   ├── test_api_projects.py
    │   ├── test_api_runs.py
    │   ├── test_api_exploration.py
    │   ├── test_api_workflow_control.py
    │   ├── test_worker_phase_runner.py
    │   ├── test_worker_orchestrator.py
    │   ├── test_websocket.py
    │   └── test_log_streaming.py
    └── e2e/
        ├── test_full_workflow_autopilot.py
        └── test_full_workflow_manual.py
```

---

## Phase 1: Foundation — Database, Config, CLI, Copilot Session

**Goal:** Bootable backend skeleton, database with migrations, and validated Copilot CLI subprocess I/O.

### 1.1 Project Bootstrap

| Task | Files |
|------|-------|
| Initialize uv project with pyproject.toml | `pyproject.toml` |
| Dependencies: fastapi, uvicorn, sqlalchemy, aiosqlite, alembic, pydantic, websockets | `pyproject.toml` |
| CLI entry point with `serve`, `worker`, `dev` subcommands (use `click` or `typer`) | `relay/cli.py` |
| Config module: `RELAY_DATA_DIR`, `RELAY_DB_PATH`, `RELAY_HOST`, `RELAY_PORT`, Copilot CLI path override | `relay/config.py` |
| Hardcoded known Copilot model list (used by settings UI and prompt construction) | `relay/copilot/models.py` |

### 1.2 Database

| Task | Files |
|------|-------|
| SQLAlchemy async engine + session factory with WAL mode and 5s busy timeout | `relay/db.py` |
| All 7 ORM models matching spec schema | `relay/models/*.py` |
| Alembic setup with async SQLAlchemy support | `alembic.ini`, `alembic/env.py` |
| Initial migration creating all tables | `alembic/versions/001_initial.py` |
| Auto-migration on server startup | `relay/api/app.py` startup event |

### 1.3 Copilot CLI Integration (Highest Risk — Do First)

| Task | Files |
|------|-------|
| Detection: check `gh` in PATH, `gh copilot --version`, `gh auth status` | `relay/copilot/detection.py` |
| `CopilotSession` class: wraps `subprocess.Popen`, provides `send(prompt) -> async iterator[str]` for streaming stdout, `kill()`, `is_alive()`, `wait() -> exit_code` | `relay/copilot/session.py` |
| Test interactive stdin/stdout with real Copilot CLI (manual spike, not automated) | — |
| If stdin follow-up works: implement `send_followup(prompt)` for session reuse | `relay/copilot/session.py` |
| If stdin follow-up doesn't work: implement "new session with accumulated context" fallback | `relay/copilot/session.py` |
| `FakeCopilotSession` that reads from canned response files, simulates streaming delays | `tests/mocks/fake_copilot.py` |

**Exit Criteria:** Can spawn a Copilot CLI subprocess, send a prompt, stream stdout chunks, detect exit. Session reuse strategy is decided and implemented.

### 1.4 Prompt Templates

| Task | Files |
|------|-------|
| Prompt templates for all 6 phases as Python string templates | `relay/copilot/prompts.py` |
| Planning prompt: include planning_prompt.md artifact, context paths, instruct to write SPEC.md + IMPLEMENTATION_PLAN.md | `relay/copilot/prompts.py` |
| Critique prompt: include SPEC.md, IMPLEMENTATION_PLAN.md, instruct inline annotation format | `relay/copilot/prompts.py` |
| Correction prompt: include critique, instruct to produce clean corrected plan | `relay/copilot/prompts.py` |
| Execution prompt: include SPEC.md, corrected plan, context paths, instruct build/test | `relay/copilot/prompts.py` |
| Review prompt: include SPEC.md, plan, instruct JSON review output format with sentinel, summary template | `relay/copilot/prompts.py` |
| Fix prompt: include review findings, SPEC.md, plan | `relay/copilot/prompts.py` |
| Exploration finalization prompt: instruct structured summary generation | `relay/copilot/prompts.py` |

### Tests (Phase 1)

- **Unit:** `test_settings_resolution.py` — config precedence logic
- **Unit:** `test_prompt_builder.py` — template rendering with various inputs
- **Integration:** Database creation, migration, WAL mode verification
- **Manual:** CopilotSession with real `gh copilot` — stdin write, stdout stream, exit detection

---

## Phase 2: Worker Core — Subprocess Supervision, State Machine, Orchestration

**Goal:** Worker can pick up a workflow, run phases in sequence using subprocess management, handle retries and cancellation.

### 2.1 Worker Main Loop

| Task | Files |
|------|-------|
| Main async loop: poll DB every 1s for actionable work | `relay/worker/main.py` |
| Determine max concurrency from CPU/RAM heuristics on startup | `relay/worker/scheduler.py` |
| Pick up `queued` workflows in FIFO order up to concurrency limit | `relay/worker/scheduler.py` |
| Track active workflows in memory: `dict[str, WorkflowContext]` | `relay/worker/main.py` |

### 2.2 Phase Runner

| Task | Files |
|------|-------|
| `run_phase(workflow_run, phase)`: spawn CopilotSession, stream stdout/stderr to log file, await exit | `relay/worker/phase_runner.py` |
| Write log file to `<relay-data-dir>/logs/<run-id>/<phase>_attempt_<n>.log` | `relay/worker/phase_runner.py` |
| Create phase_attempt row at start (status=running, pid, log_file_path, rendered_prompt) | `relay/worker/phase_runner.py` |
| Update phase_attempt on exit (status, exit_code, ended_at, error_message) | `relay/worker/phase_runner.py` |
| Non-blocking stdout/stderr read using `asyncio.create_subprocess_exec` or thread-based pipe reader | `relay/worker/phase_runner.py` |

### 2.3 Orchestrator — State Machine

| Task | Files |
|------|-------|
| `advance_workflow(run)`: given current state, determine and execute next action | `relay/worker/orchestrator.py` |
| Phase sequencing: Exploration→Planning→Critique→Correction→Execution→Review | `relay/worker/orchestrator.py` |
| Session reuse tracking: keep Planning subprocess alive for Correction, Execution subprocess alive for fix loops | `relay/worker/orchestrator.py` |
| Autopilot vs non-autopilot: check pause points, set workflow status to `waiting_for_user` | `relay/worker/orchestrator.py` |
| Review verdict parsing: read REVIEW_SUMMARY.md, extract verdict | `relay/worker/orchestrator.py` |
| Review-fix loop: increment counter, check limit, route back to Execution or complete | `relay/worker/orchestrator.py` |
| Terminal states: set `completed`, `completed_with_unresolved_findings`, `failed` | `relay/worker/orchestrator.py` |

### 2.4 Retry Logic

| Task | Files |
|------|-------|
| Exponential backoff: `delay = min(5 * 2^(attempt-1), 120)` | `relay/worker/retry.py` |
| Retry on non-zero exit, crash, process_lost | `relay/worker/retry.py` |
| Track retry count per phase, respect retry_limit from run settings | `relay/worker/retry.py` |
| On retries exhausted: fail phase, fail workflow | `relay/worker/retry.py` |

### 2.5 Process Monitor

| Task | Files |
|------|-------|
| Periodic check (every 10s): verify tracked PIDs are alive via `os.kill(pid, 0)` or `psutil.pid_exists` | `relay/worker/process_monitor.py` |
| On ghost detected: mark phase failed with `process_lost`, trigger retry | `relay/worker/process_monitor.py` |
| On worker startup: scan DB for `running`/`starting` phases, check PIDs, re-adopt or fail | `relay/worker/process_monitor.py` |

### 2.6 Cancellation

| Task | Files |
|------|-------|
| Worker polls for `cancel_requested` flag on workflow_runs (set by API) | `relay/worker/main.py` |
| On cancel: `session.kill()`, set phase status `cancelled`, set workflow status `cancelled` | `relay/worker/orchestrator.py` |

### 2.7 Git Operations

| Task | Files |
|------|-------|
| `is_git_repo(path)`: check `.git` or `git rev-parse` | `relay/worker/git_ops.py` |
| `create_branch(path, branch_name, from_commit)`: `git checkout -b relay/<run-id>` | `relay/worker/git_ops.py` |
| `get_head_commit(path)`: `git rev-parse HEAD` | `relay/worker/git_ops.py` |
| Called by orchestrator before Execution phase starts | `relay/worker/orchestrator.py` |

### 2.8 Artifact Management

| Task | Files |
|------|-------|
| `ensure_artifact_dirs(project_path, run_id)`: create `.relay/<run-id>/...` folder tree | `relay/artifacts/manager.py` |
| `save_artifact(project_path, run_id, phase, filename, content)` | `relay/artifacts/manager.py` |
| `read_artifact(project_path, run_id, phase, filename) -> str` | `relay/artifacts/manager.py` |
| `archive_attempt(project_path, run_id, phase, attempt_number)`: copy current phase artifacts to `attempts/` subfolder | `relay/artifacts/manager.py` |
| `check_artifacts_exist(project_path, run_id, phase, expected_files) -> bool` | `relay/artifacts/manager.py` |
| Review output parser: extract JSON from sentinel-fenced block, parse verdict from summary, fallback to raw | `relay/artifacts/parsers.py` |
| Exploration artifacts: write message JSON files, generate transcript.md, generate planning_prompt.md | `relay/artifacts/exploration.py` |

### Tests (Phase 2)

- **Unit:** `test_state_machine.py` — all workflow/phase transitions, edge cases (rerun from stale, cancel during retry)
- **Unit:** `test_retry.py` — backoff timing, retry exhaustion, counter reset on rerun
- **Unit:** `test_scheduler.py` — concurrency heuristic, FIFO ordering, slot management
- **Unit:** `test_artifact_parser.py` — review JSON extraction, verdict parsing, malformed input fallback
- **Unit:** `test_git_ops.py` — branch creation, non-git detection
- **Integration:** `test_worker_phase_runner.py` — run FakeCopilotSession through phase_runner, verify log file, DB updates
- **Integration:** `test_worker_orchestrator.py` — full workflow with FakeCopilotSession, verify phase progression, autopilot vs manual, review-fix loop, retry, cancel

---

## Phase 3: API Layer

**Goal:** All REST endpoints operational, connected to DB and worker via database commands.

### 3.1 FastAPI App Factory

| Task | Files |
|------|-------|
| App factory with lifespan (DB init, migration, Copilot detection) | `relay/api/app.py` |
| Mount all routers under `/api/v1` | `relay/api/app.py` |
| CORS middleware for dev (localhost frontend) | `relay/api/app.py` |
| Static file serving for frontend build output | `relay/api/app.py` |

### 3.2 Pydantic Schemas

| Task | Files |
|------|-------|
| All request/response models matching spec Section 14.2 | `relay/schemas/*.py` |
| Enums for workflow status, phase status, phase type, severity | `relay/schemas/run.py`, `relay/schemas/phase.py` |

### 3.3 Service Layer

| Task | Files |
|------|-------|
| `ProjectService`: create (validate path, detect git), list, get, update, delete, browse file tree | `relay/services/project_service.py` |
| `RunService`: create (resolve settings from precedence chain, pre-create all 6 phase rows), list, get, delete | `relay/services/run_service.py` |
| `PhaseService`: get phase, get attempt, get logs (paginated read from log file) | `relay/services/phase_service.py` |
| `SettingsService`: get/set user_settings, get effective settings for project or run | `relay/services/settings_service.py` |

### 3.4 API Routers

| Task | Files |
|------|-------|
| System: `GET /health` (DB ping, Copilot status), `GET /system/status` | `relay/api/system.py` |
| Projects: full CRUD + `GET /projects/{id}/files` (file tree as JSON) + settings endpoints | `relay/api/projects.py` |
| Runs: `GET /runs` (with filters), `POST /runs`, `GET /runs/{id}`, `DELETE /runs/{id}` | `relay/api/runs.py` |
| Phases: list, detail, attempt detail, logs, prompt | `relay/api/phases.py` |
| Exploration: `POST messages`, `GET messages`, `POST finalize`, `PUT context`, `GET context` | `relay/api/exploration.py` |
| Workflow control: `POST advance`, `POST cancel`, `POST rerun`, `POST review/approve`, `POST review/fix` | `relay/api/workflow_control.py` |
| Artifacts: `GET /runs/{run_id}/artifacts/{path}` — serve file from `.relay/<run-id>/` | `relay/api/artifacts.py` |
| Settings: `GET /settings`, `PUT /settings` | `relay/api/settings.py` |

### 3.5 Exploration Message Handling

| Task | Files |
|------|-------|
| `POST /runs/{run_id}/exploration/messages`: save user message to DB, signal worker to send to Copilot session | `relay/api/exploration.py` |
| The worker picks up pending exploration messages and feeds them to the Copilot session | `relay/worker/orchestrator.py` |
| Exploration phase is special: worker keeps the session alive, polls DB for new user messages | `relay/worker/phase_runner.py` |
| `POST /runs/{run_id}/exploration/finalize`: set finalization flag in DB, worker sends finalization prompt | `relay/api/exploration.py` |

### 3.6 Workflow Control Commands

| Task | Files |
|------|-------|
| `cancel`: set `cancel_requested=true` on workflow_runs row | `relay/api/workflow_control.py` |
| `advance`: validate workflow is `waiting_for_user`, set flag for worker to proceed | `relay/api/workflow_control.py` |
| `rerun`: validate phase is rerunnable, reset phase to `queued`, mark downstream `stale`, set workflow to `running` | `relay/api/workflow_control.py` |
| `review/approve`: set workflow to `completed` or `completed_with_unresolved_findings` | `relay/api/workflow_control.py` |
| `review/fix`: save fix prompt (edited or default), set flag for worker to route to Execution | `relay/api/workflow_control.py` |

### Tests (Phase 3)

- **Integration:** `test_api_projects.py` — CRUD, validation (bad path, duplicate path), file tree browsing
- **Integration:** `test_api_runs.py` — create with settings resolution, list with filters, delete guards
- **Integration:** `test_api_exploration.py` — message flow, finalize guards (streaming, already finalized)
- **Integration:** `test_api_workflow_control.py` — cancel, advance, rerun (valid and invalid states), approve, fix

---

## Phase 4: WebSocket and Real-Time Layer

**Goal:** Live status updates, log streaming, and exploration chat streaming over WebSocket.

### 4.1 WebSocket Infrastructure

| Task | Files |
|------|-------|
| WebSocket endpoint at `/api/v1/ws` | `relay/api/ws.py` |
| `ConnectionManager`: track connections, subscription sets (per-run, subscribe_all) | `relay/realtime/connection_manager.py` |
| Handle client messages: `subscribe`, `unsubscribe`, `subscribe_all` | `relay/api/ws.py` |
| Broadcast helper: send event to all connections subscribed to a given run_id | `relay/realtime/connection_manager.py` |

### 4.2 DB-to-WebSocket Bridge (Status Events)

| Task | Files |
|------|-------|
| `StatusNotifier`: async task that polls DB every 1s for workflow/phase status changes since last check | `relay/realtime/notifier.py` |
| Track last-seen status per workflow/phase in memory | `relay/realtime/notifier.py` |
| On change: build `workflow_status` or `phase_status` event, broadcast to subscribers | `relay/realtime/notifier.py` |
| Also emit `review_results` event when review phase succeeds | `relay/realtime/notifier.py` |
| Also emit `error` events on phase failure | `relay/realtime/notifier.py` |

### 4.3 Log Streaming

| Task | Files |
|------|-------|
| `LogTailer`: async generator that tails a log file, yields new lines | `relay/realtime/log_tailer.py` |
| When a client subscribes to a run and a phase is actively running: start a LogTailer for that phase's log file | `relay/api/ws.py` |
| Emit `log` events per line | `relay/api/ws.py` |
| Stop tailing when phase exits or client unsubscribes | `relay/realtime/log_tailer.py` |

### 4.4 Exploration Streaming

| Task | Files |
|------|-------|
| Worker streams Copilot stdout chunks for Exploration to a dedicated streaming mechanism | `relay/worker/phase_runner.py` |
| Option A (preferred): Worker writes chunks to a dedicated streaming file (`exploration_stream.jsonl`), server tails it | `relay/worker/phase_runner.py`, `relay/realtime/log_tailer.py` |
| Emit `exploration_chunk` events with `message_id`, `content`, `done` | `relay/api/ws.py` |
| On stream complete: save full assistant message to DB, emit final `done=true` chunk | `relay/worker/phase_runner.py` |
| On exploration finalized: emit `exploration_finalized` event | `relay/realtime/notifier.py` |

### Tests (Phase 4)

- **Integration:** `test_websocket.py` — connect, subscribe, receive status events on workflow state changes
- **Integration:** `test_log_streaming.py` — write to log file, verify WebSocket client receives lines
- **Unit:** LogTailer — tail behavior, new lines, file rotation edge case

---

## Phase 5: Frontend

**Goal:** Complete UI matching spec Section 16.

### 5.1 Project Setup

| Task | Files |
|------|-------|
| Vite + React + TypeScript scaffold | `frontend/` |
| Dependencies: react-router-dom, zustand (state), @tanstack/react-query (data fetching), tailwindcss, shadcn/ui, lucide-react (icons), react-markdown, highlight.js | `frontend/package.json` |
| API client module: base URL from env, typed fetch wrappers | `frontend/src/api/client.ts` |
| WebSocket client: connect, reconnect, message parsing, subscription management | `frontend/src/api/ws.ts` |
| TypeScript types mirroring Pydantic schemas | `frontend/src/types/api.ts`, `frontend/src/types/ws.ts` |

### 5.2 Layout and Navigation

| Task | Files |
|------|-------|
| `AppShell`: sidebar or top nav, route outlet | `frontend/src/components/layout/AppShell.tsx` |
| `Navbar`: logo, Projects/Runs/Settings links, AutopilotToggle, Copilot status dot | `frontend/src/components/layout/Navbar.tsx` |
| `AutopilotToggle`: reads/writes settings API, persists | `frontend/src/components/layout/AutopilotToggle.tsx` |
| React Router setup: `/projects`, `/projects/:id`, `/projects/:id/workflows/new`, `/runs`, `/runs/:id`, `/settings` | `frontend/src/App.tsx` |

### 5.3 Shared Components

| Task | Files |
|------|-------|
| `StatusBadge`: color-coded status chip (maps status enum to color/icon) | `frontend/src/components/shared/StatusBadge.tsx` |
| `LogViewer`: monospace log display, auto-scroll with scroll-lock, load-more pagination | `frontend/src/components/shared/LogViewer.tsx` |
| `MarkdownRenderer`: renders Markdown with syntax highlighting | `frontend/src/components/shared/MarkdownRenderer.tsx` |
| `ConfirmDialog`: generic modal for destructive actions | `frontend/src/components/shared/ConfirmDialog.tsx` |

### 5.4 Projects Pages

| Task | Files |
|------|-------|
| `ProjectsListPage`: card grid, "Add Project" modal (path input, validates via API) | `frontend/src/pages/ProjectsListPage.tsx` |
| `ProjectDetailPage`: tabs (Overview, Runs, Configuration) | `frontend/src/pages/ProjectDetailPage.tsx` |
| Overview tab: project info, git info, active runs count, "New Workflow" button | — (inline in ProjectDetailPage) |
| Runs tab: runs table, click navigates to `/runs/:id` | — |
| Configuration tab: model mapping table, retry/loop/autopilot overrides with "use default" toggles | — |

### 5.5 New Workflow Page

| Task | Files |
|------|-------|
| `NewWorkflowPage`: workflow name input, collapsible advanced section, "Create & Start" button | `frontend/src/pages/NewWorkflowPage.tsx` |
| Advanced: phase model mapping table, retry count, loop limit, autopilot toggle | — |
| On submit: `POST /runs`, navigate to `/runs/:id` | — |

### 5.6 Run Detail Page — Core Layout

| Task | Files |
|------|-------|
| `RunDetailPage`: two-column layout (left: phase graph, right: detail panel) | `frontend/src/pages/RunDetailPage.tsx` |
| Subscribe to WebSocket for this run on mount, unsubscribe on unmount | `frontend/src/hooks/useRunStatus.ts` |
| `PhaseGraph`: vertical list of `PhaseNode` components with connectors | `frontend/src/components/workflow/PhaseGraph.tsx` |
| `PhaseNode`: name, status badge, duration, attempt count badge, click handler, pulsing animation for running | `frontend/src/components/workflow/PhaseNode.tsx` |
| `ReviewFixLoopIndicator`: visual arc from Review back to Execution with counter | `frontend/src/components/workflow/ReviewFixLoopIndicator.tsx` |
| `WorkflowSummary`: default right panel content (name, status, branch, timing, context paths) | `frontend/src/components/detail-panel/WorkflowSummary.tsx` |

### 5.7 Phase Detail Panel

| Task | Files |
|------|-------|
| `PhaseDetailPanel`: header (name, status, timing) + tabbed content | `frontend/src/components/detail-panel/PhaseDetailPanel.tsx` |
| `PhaseSummaryTab`: phase outcome, artifact previews (rendered Markdown) | `frontend/src/components/detail-panel/PhaseSummaryTab.tsx` |
| `PhasePromptTab`: rendered prompt (read-only, syntax highlighted) | `frontend/src/components/detail-panel/PhasePromptTab.tsx` |
| `PhaseLogsTab`: `LogViewer` wired to WebSocket log stream (live) or log file API (historical) | `frontend/src/components/detail-panel/PhaseLogsTab.tsx` |
| `ReviewCommentsTab`: table of file, line, severity, comment | `frontend/src/components/detail-panel/ReviewCommentsTab.tsx` |
| `AttemptHistoryTab`: list of attempts with status, timing, click to switch viewed attempt | `frontend/src/components/detail-panel/AttemptHistoryTab.tsx` |

### 5.8 Exploration UI

| Task | Files |
|------|-------|
| `ChatThread`: message list with user/assistant bubbles, auto-scroll | `frontend/src/components/exploration/ChatThread.tsx` |
| `ChatInput`: text area, send button (disabled during streaming), keyboard submit | `frontend/src/components/exploration/ChatInput.tsx` |
| `useExplorationChat` hook: send message via API, handle `exploration_chunk` WebSocket events for streaming, accumulate partial content | `frontend/src/hooks/useExplorationChat.ts` |
| `ContextPanel`: slide-in panel with `FileTreeBrowser` | `frontend/src/components/exploration/ContextPanel.tsx` |
| `FileTreeBrowser`: lazy-loaded file tree from `GET /projects/{id}/files`, checkboxes for selection, folder-level selection | `frontend/src/components/exploration/FileTreeBrowser.tsx` |
| `FinalizeButton`: disabled during streaming, confirms finalization | `frontend/src/components/exploration/FinalizeButton.tsx` |
| `PlanningPromptView`: read-only Markdown render of planning_prompt.md after finalization | `frontend/src/components/exploration/PlanningPromptView.tsx` |
| When Exploration is active: main area switches from PhaseGraph to chat layout, graph becomes compact sidebar | `frontend/src/pages/RunDetailPage.tsx` |

### 5.9 Review Approval UI

| Task | Files |
|------|-------|
| `ReviewApprovalBar`: shown when workflow is `waiting_for_user` after Review | `frontend/src/components/review/ReviewApprovalBar.tsx` |
| Buttons: "Approve & Complete", "Send to Fix", "Cancel Workflow" | — |
| `FixPromptEditor`: modal/drawer with editable textarea pre-populated with default fix prompt, confirm button | `frontend/src/components/review/FixPromptEditor.tsx` |

### 5.10 Other Pause Point UIs

| Task | Files |
|------|-------|
| After Exploration finalized (non-autopilot): "Start Planning" action bar in detail panel | `frontend/src/pages/RunDetailPage.tsx` |
| After Plan Critique (non-autopilot): "Continue to Plan Correction" action bar | `frontend/src/pages/RunDetailPage.tsx` |
| Rerun controls: "Restart from this phase" button on failed/cancelled phases | `frontend/src/components/detail-panel/PhaseDetailPanel.tsx` |

### 5.11 Runs List and Settings Pages

| Task | Files |
|------|-------|
| `RunsListPage`: table with project, name, status, date, duration. Filters by project/status. | `frontend/src/pages/RunsListPage.tsx` |
| `SettingsPage`: sections for General, Models, Autopilot, Retry/Loop Limits | `frontend/src/pages/SettingsPage.tsx` |
| Hook up to `GET/PUT /settings` | — |

### 5.12 Hooks and State

| Task | Files |
|------|-------|
| `useWebSocket`: manage connection lifecycle, reconnect, parse messages, dispatch to subscribers | `frontend/src/hooks/useWebSocket.ts` |
| `useRunStatus`: subscribe to a run_id, update local run state from WebSocket events | `frontend/src/hooks/useRunStatus.ts` |
| `useLogStream`: subscribe to log events for a specific phase/attempt | `frontend/src/hooks/useLogStream.ts` |
| `settingsStore`: global autopilot state, theme | `frontend/src/store/settingsStore.ts` |
| `runStore`: currently viewed run, selected phase | `frontend/src/store/runStore.ts` |

### Tests (Phase 5)

- Frontend testing is primarily manual for v1.
- Validate all pages render with mock API data.
- Validate WebSocket reconnection behavior.
- Validate Exploration chat streaming UX (responsiveness, send-button locking, finalization).

---

## Phase 6: Integration, Docker, and Polish

**Goal:** End-to-end flows work. Docker image builds. Everything is wired together.

### 6.1 Frontend Build Integration

| Task | Files |
|------|-------|
| Vite build output to `frontend/dist/` | `frontend/vite.config.ts` |
| FastAPI serves `frontend/dist/` as static files at `/` | `relay/api/app.py` |
| SPA fallback: all non-API routes serve `index.html` | `relay/api/app.py` |

### 6.2 Docker

| Task | Files |
|------|-------|
| Dockerfile: multi-stage (Node build frontend, Python install backend) | `Dockerfile` |
| Base image: `python:3.12-slim` | `Dockerfile` |
| Install `gh` CLI + Copilot extension in image | `Dockerfile` |
| Install `uv`, copy project, `uv sync` | `Dockerfile` |
| Install Node, build frontend | `Dockerfile` |
| Document volume mounts: project folders + `~/.config/gh/` for auth credentials | `docker-compose.yml`, README |
| Entrypoint: `relay` CLI | `Dockerfile` |
| `docker-compose.yml` for dev: server + worker as separate services, shared volume for DB and logs | `docker-compose.yml` |
| `docker-compose.yml` for prod: single service running `relay dev` mode (both in one process) | `docker-compose.yml` |

### 6.3 End-to-End Wiring

| Task | Files |
|------|-------|
| Verify: create project → create workflow → Exploration chat → finalize → autopilot through all phases → complete | Manual testing |
| Verify: non-autopilot flow with all pause points | Manual testing |
| Verify: phase failure → retry → success | Using FakeCopilotSession configured to fail N times |
| Verify: cancel mid-execution | Manual testing |
| Verify: rerun from failed phase, verify stale marking | Manual testing |
| Verify: review-fix loop (autopilot), verify loop counter and max limit | Using FakeCopilotSession |
| Verify: concurrent workflows on different projects | Manual testing |
| Verify: concurrent workflows on same non-git project shows warning | Manual testing |
| Verify: git branch creation at Execution start | Manual testing on git repo |

### 6.4 Polish

| Task | Files |
|------|-------|
| Copilot CLI missing banner in UI | `frontend/src/components/layout/Navbar.tsx` |
| Non-git concurrent workflow warning | `frontend/src/pages/RunDetailPage.tsx`, `frontend/src/pages/ProjectDetailPage.tsx` |
| Project path invalid warning on project detail | `frontend/src/pages/ProjectDetailPage.tsx` |
| Dark/light mode toggle (CSS variables + system preference) | `frontend/src/components/layout/AppShell.tsx`, CSS |
| Error boundaries / empty states for all pages | Various |
| Loading skeletons for data-fetching pages | Various |

---

## Phase 7: Automated Testing Suite

**Goal:** Sufficient automated test coverage for confident deployment.

### 7.1 Unit Tests

| Test File | Covers |
|-----------|--------|
| `test_state_machine.py` | All workflow/phase status transitions including edge cases |
| `test_retry.py` | Backoff calculation, retry counting, exhaustion, reset on rerun |
| `test_scheduler.py` | Concurrency heuristic math, FIFO queue, slot tracking |
| `test_prompt_builder.py` | All 8 prompt templates with various input combinations |
| `test_artifact_parser.py` | Review JSON extraction (valid, malformed, missing), verdict parsing, fallback |
| `test_settings_resolution.py` | 4-level precedence chain, null overrides, empty strings |
| `test_git_ops.py` | Branch creation, HEAD resolution, non-git detection |

### 7.2 Integration Tests

| Test File | Covers |
|-----------|--------|
| `test_api_projects.py` | CRUD, path validation, git detection, file tree |
| `test_api_runs.py` | Create with settings resolution, list filters, delete guards |
| `test_api_exploration.py` | Message persistence, finalize flow, context selection |
| `test_api_workflow_control.py` | Cancel, advance, rerun (valid + invalid), approve, fix |
| `test_worker_phase_runner.py` | Phase execution with FakeCopilotSession, log file output, DB updates |
| `test_worker_orchestrator.py` | Full workflow progression, autopilot, manual, review-fix loop, retry, cancel |
| `test_websocket.py` | Subscribe, receive events, unsubscribe, reconnect |
| `test_log_streaming.py` | File tail → WebSocket delivery |

### 7.3 End-to-End Tests

| Test File | Covers |
|-----------|--------|
| `test_full_workflow_autopilot.py` | Create project → run workflow → auto-complete (FakeCopilotSession) |
| `test_full_workflow_manual.py` | Full non-autopilot flow with explicit advances and review approval |

### Test Infrastructure

| Item | Detail |
|------|--------|
| Test DB | In-memory SQLite per test via fixture |
| FakeCopilotSession | Configurable: success/failure, canned stdout, streaming delay, exit code |
| Test factories | `factories.py`: create_project, create_run, create_phase, etc. with sensible defaults |
| CI | GitHub Actions: `uv run pytest`, frontend `npm test` (if added later) |

---

## MVP Rollout Order

This is the order in which to build and validate for the fastest path to a working demo.

| Step | What | Validates |
|------|------|-----------|
| **1** | Phase 1.1 + 1.2 | Project boots, DB works |
| **2** | Phase 1.3 | Copilot subprocess I/O proven (critical risk retired) |
| **3** | Phase 2.1 + 2.2 + 2.8 | Worker runs a single phase with FakeCopilot, writes logs and artifacts |
| **4** | Phase 2.3 + 2.4 | Full workflow progression end-to-end in worker (FakeCopilot) |
| **5** | Phase 3.1-3.4 | API serves project/run/phase data |
| **6** | Phase 3.5 + 3.6 | Exploration + workflow control endpoints work |
| **7** | Phase 4.1 + 4.2 | Live status updates via WebSocket |
| **8** | Phase 5.1-5.3 + 5.4 | Minimal frontend: projects page, can add project |
| **9** | Phase 5.5 + 5.6 + 5.7 | Run detail page: graph + detail panel (read-only viewing of a run) |
| **10** | Phase 5.8 | Exploration chat UI (interactive — first time a user can drive a workflow from UI) |
| **11** | Phase 4.3 + 4.4 + 5.7 (LogsTab) | Live log streaming in UI |
| **12** | Phase 5.9 + 5.10 + 5.11 | Review approval, pause points, runs list, settings |
| **13** | Phase 2.5 + 2.6 | Process monitor + cancellation (needed for production use, not demos) |
| **14** | Phase 6 | Docker, e2e wiring, polish |
| **15** | Phase 7 | Automated test suite filled out |

**First demo-able milestone:** After step 10, a user can create a project, start a workflow, chat in Exploration, finalize, and watch phases progress through the UI.

**First production-usable milestone:** After step 14, all features work end-to-end in Docker with real Copilot CLI.

---

## Testing Strategy Summary

| Layer | Tool | Coverage Target |
|-------|------|----------------|
| Unit (Python) | pytest | State machine, retry logic, parsers, settings resolution, prompt building |
| Integration (Python) | pytest + httpx (TestClient) + aiosqlite | All API endpoints, worker orchestration, WebSocket events |
| E2E (Python) | pytest with FakeCopilotSession | Full workflow flows (autopilot, manual, failure, rerun) |
| E2E (Real) | Manual | Real Copilot CLI, Docker deployment, concurrent workflows |
| Frontend | Manual + optional Playwright later | All pages render, WebSocket reconnect, Exploration chat UX, action buttons |

Tests always use FakeCopilotSession except for dedicated real-CLI integration tests run manually. This keeps the test suite fast and deterministic.
