# Relay

Relay is a self-hostable AI workflow orchestration app for running multi-phase implementation workflows against local projects. It combines:

- A FastAPI backend and SQLite state store
- An async worker that executes workflow phases and retries failures
- A Vite/React frontend for project registration, exploration, run tracking, logs, and review handling
- GitHub CLI + GitHub Copilot CLI as the execution engine for exploration, planning, execution, and review

The application is currently version `0.1.0`.

## What Relay Does

Relay drives a project through these phases:

1. `exploration`
2. `planning`
3. `plan_critique`
4. `plan_correction`
5. `execution`
6. `review`

At a high level:

- Exploration is an interactive chat session with selected project files/folders as context.
- Finalizing exploration writes a planning brief to `.relay/<run_id>/exploration/planning_prompt.md`.
- Planning produces `SPEC.md` and `IMPLEMENTATION_PLAN.md`.
- Plan critique produces a critiqued plan with inline markers.
- Plan correction rewrites the plan into a clean corrected implementation plan.
- Execution applies changes directly to the working tree.
- Review emits structured review comments plus a review summary and verdict.

Relay supports:

- `autopilot` mode, which automatically advances through approval gates
- Manual pause points after exploration and plan critique
- Review-fix loops driven by review findings
- Per-phase model selection
- Retries with exponential backoff
- Realtime workflow, phase, log, and exploration-stream updates over WebSocket

## Architecture

### Backend

The backend lives in [`relay/`](./relay) and is built with:

- FastAPI
- SQLAlchemy async + `aiosqlite`
- Alembic
- Typer
- Uvicorn

Key runtime pieces:

- `relay/cli.py`: CLI entrypoints
- `relay/api/app.py`: FastAPI app creation, dependency wiring, migration-on-start, and frontend static serving
- `relay/worker/main.py`: worker loop and scheduling
- `relay/worker/orchestrator.py`: workflow state machine and phase transitions
- `relay/worker/phase_runner.py`: Copilot session execution, prompts, artifacts, logs, and review parsing
- `relay/services/`: project, run, phase, and settings services
- `relay/realtime/`: WebSocket subscription management, status notifier, and log tailing

### Frontend

The frontend lives in [`frontend/`](./frontend) and is built with:

- React 18
- TypeScript
- Vite
- TanStack Query
- React Router
- Zustand
- Tailwind CSS
- shadcn/ui-style component primitives

UI pages include:

- Projects list and project detail/configuration
- New workflow creation
- Global runs list
- Run detail with phase graph, prompts, logs, exploration chat, and review actions
- Global settings

### Persistence and Artifacts

Relay stores state in two places:

- SQLite database:
  - default path: `~/.relay/relay.db`
  - controlled by `RELAY_DB_PATH` or indirectly by `RELAY_DATA_DIR`
- Per-project workflow artifacts:
  - stored under `<project>/.relay/<run_id>/...`

Artifact layout is phase-oriented:

- `exploration/`
- `planning/`
- `critique/`
- `execution/`
- `review/`
- `attempts/`

Runtime logs are stored under:

- `<RELAY_DATA_DIR>/logs/<run_id>/`

That directory contains:

- phase attempt log files such as `planning_attempt_1.log`
- `exploration_stream.jsonl` for live exploration assistant chunks

## Workflow Behavior

### Manual vs Autopilot

If `autopilot` is disabled:

- exploration pauses after finalization
- plan critique pauses after critique
- review pauses for explicit user action

If `autopilot` is enabled:

- exploration advances directly into planning
- critique advances directly into correction
- review can:
  - complete immediately on `PASS`
  - complete as `completed_with_unresolved_findings` on `PASS_WITH_WARNINGS`
  - enter a review-fix loop on `FAIL`

### Review-Fix Loop

When review fails in autopilot mode:

- Relay builds a fix prompt from review comments, review summary, `SPEC.md`, corrected implementation plan, and selected context paths.
- Execution is queued again.
- Review is re-run.
- The loop stops once review passes or `review_fix_loop_limit` is reached.

### Git Behavior

If the registered project is a git repository:

- Relay captures the HEAD commit when the run is created.
- Execution creates or resets a branch named `relay/<run_id>` from that commit before code changes are applied.

If the project is not a git repo:

- The run still works, but no branch is created.

## Requirements

### Backend

- Python `3.12+`
- `uv`

### Frontend

- Node.js `20+`
- npm

### AI Runtime

- GitHub CLI (`gh`)
- GitHub Copilot CLI extension:
  - `gh extension install github/gh-copilot`
- Authenticated GitHub CLI session:
  - `gh auth login`

If `gh` or Copilot is unavailable, the UI will show a warning banner and workflow phases that depend on Copilot will not run successfully.

## Quick Start

### 1. Install backend dependencies

From the repository root:

```bash
uv sync --dev
```

This installs application and test dependencies from `pyproject.toml` and `uv.lock`.

### 2. Install frontend dependencies

```bash
cd frontend
npm ci
```

### 3. Make sure GitHub Copilot CLI is ready

```bash
gh auth status
gh copilot --version
```

If the extension is missing:

```bash
gh extension install github/gh-copilot
```

## Running the App

### Option A: Full local development workflow

Start the backend API and worker together:

```bash
uv run relay dev
```

In a second terminal, start the Vite frontend:

```bash
cd frontend
npm run dev
```

Open:

- Frontend dev server: `http://127.0.0.1:5173`
- Backend API: `http://127.0.0.1:8080`

In this mode:

- Vite proxies `/api` to `http://127.0.0.1:8080`
- CORS is enabled for `http://localhost:5173` and `http://127.0.0.1:5173`
- `relay dev` runs both the FastAPI server and the async worker in one process

### Option B: Split API and worker processes

Terminal 1:

```bash
uv run relay serve
```

Terminal 2:

```bash
uv run relay worker
```

Terminal 3:

```bash
cd frontend
npm run dev
```

Use this if you want the API and worker isolated during development.

### Option C: Serve the built frontend from FastAPI

Build the frontend:

```bash
cd frontend
npm run build
```

Then start the backend:

```bash
uv run relay serve
```

Open:

- `http://127.0.0.1:8080`

FastAPI will serve `frontend/dist/index.html` and `/assets/*` automatically if the build output exists.

## CLI Commands

Relay exposes three Typer commands:

```bash
uv run relay --help
```

Commands:

- `uv run relay serve`
  - Run the FastAPI application only
- `uv run relay worker`
  - Run the background workflow worker only
- `uv run relay dev`
  - Run server + worker together

## Build Instructions

### Frontend production build

```bash
cd frontend
npm run build
```

This runs:

- `tsc -b`
- `vite build`

Output goes to:

- `frontend/dist/`

### Python package build

```bash
uv build
```

Output goes to:

- `dist/relay-0.1.0.tar.gz`
- `dist/relay-0.1.0-py3-none-any.whl`

### Docker image build

```bash
docker build -t relay .
```

The Dockerfile:

- builds the frontend in a Node 20 stage
- installs Python 3.12 dependencies with `uv`
- installs `gh`
- installs the `github/gh-copilot` extension
- copies the built frontend into `frontend/dist`
- starts Relay with `uv run relay dev`

## Docker Compose

There is a `docker-compose.yml` for running Relay in a container:

```bash
docker compose up --build
```

Important details:

- The app is exposed on `8080`.
- The container stores Relay data in a named volume mounted at `/data`.
- The compose file expects a GitHub CLI config mount at `${HOME}/.config/gh:/root/.config/gh:ro`.
- The compose file also expects your target projects to be mounted under `/path/to/projects:/projects`.

Before using the compose file, edit the bind mount:

- replace `/path/to/projects` with a real host directory containing projects you want Relay to work on

On Windows, be careful with `${HOME}`:

- if `HOME` is not defined, Docker Compose will warn and substitute an empty value
- in PowerShell you can set it before running compose:

```powershell
$env:HOME = $env:USERPROFILE
docker compose up --build
```

Or update the compose file to use a Windows-appropriate path directly.

## Database and Migrations

The FastAPI app automatically runs Alembic migrations on startup.

That means:

- you normally do not need a separate migration step for local development
- the database file and parent directories are created automatically
- SQLite is configured with:
  - WAL journal mode
  - foreign keys enabled
  - a 5-second busy timeout

## Configuration

Runtime behavior is controlled primarily by environment variables.

| Variable | Default | Purpose |
| --- | --- | --- |
| `RELAY_DATA_DIR` | `~/.relay` | Base directory for runtime state and logs |
| `RELAY_DB_PATH` | `<RELAY_DATA_DIR>/relay.db` | SQLite database path |
| `RELAY_FRONTEND_DIST` | `<repo>/frontend/dist` | Built frontend directory served by FastAPI |
| `RELAY_HOST` | `127.0.0.1` | API bind host |
| `RELAY_PORT` | `8080` | API bind port |
| `RELAY_COPILOT_CLI_PATH` | `gh` | Executable used to invoke GitHub CLI |
| `RELAY_POLL_INTERVAL` | `1.0` | Worker loop poll interval in seconds |
| `RELAY_PROCESS_MONITOR_INTERVAL` | `10.0` | How often the worker checks tracked subprocess health |
| `RELAY_DEFAULT_RETRY_LIMIT` | `5` | Default max retries per phase |
| `RELAY_DEFAULT_REVIEW_FIX_LOOP_LIMIT` | `5` | Default max review-fix loop iterations |
| `RELAY_DEFAULT_AUTOPILOT` | `true` | Global default autopilot state |

### Settings precedence

Run settings are resolved in this order:

1. Explicit run overrides
2. Project-level overrides
3. User/global settings
4. Application defaults from environment/config

This applies to:

- per-phase model mapping
- retry limit
- review-fix loop limit
- autopilot

## Frontend and API Notes

### Frontend API base URL

The frontend uses:

- `VITE_API_BASE_URL` if defined
- otherwise `/api/v1`

During local Vite development, `/api` is proxied to `http://127.0.0.1:8080`.

### WebSocket endpoint

Realtime updates use:

- `/api/v1/ws`

WebSocket events include:

- `workflow_status`
- `phase_status`
- `log`
- `exploration_chunk`
- `review_results`
- `exploration_finalized`
- `error`

### API surface

The backend groups routes under `/api/v1`:

- `/projects`
- `/runs`
- `/runs/{run_id}/exploration`
- `/runs/{run_id}/phases`
- `/runs/{run_id}/artifacts`
- `/runs/{run_id}/advance`
- `/runs/{run_id}/cancel`
- `/runs/{run_id}/rerun`
- `/runs/{run_id}/review/*`
- `/settings`
- `/health`
- `/system/status`
- `/ws`

## Developer Workflow

### Typical local loop

1. Start Relay:

```bash
uv run relay dev
```

2. Start the frontend:

```bash
cd frontend
npm run dev
```

3. Open the UI and:
   - register a project using an absolute path
   - create a workflow
   - chat in exploration
   - choose context paths
   - finalize exploration
   - review planning, execution, and review output

### Where to look while developing

- API contracts: `relay/api/` and `relay/schemas/`
- workflow logic: `relay/worker/orchestrator.py`
- prompt generation: `relay/copilot/prompts.py`
- persisted artifacts: `<project>/.relay/<run_id>/`
- run logs: `<RELAY_DATA_DIR>/logs/<run_id>/`
- frontend data fetching: `frontend/src/api/`
- run UI: `frontend/src/pages/RunDetailPage.tsx`

## Testing

### Backend test suite

Run all tests:

```bash
uv run pytest
```

The current suite covers:

- end-to-end manual and autopilot workflow paths
- API endpoints
- worker orchestration
- phase execution and artifact persistence
- WebSocket broadcasting and log tailing
- retry logic
- settings precedence
- transition/state-machine enforcement
- git helper behavior
- prompt construction

Validation result in this workspace on March 29, 2026:

- `uv run pytest` passed: `116 passed`

### Frontend validation

There is currently no dedicated frontend test script in `frontend/package.json`.

The implemented frontend validation path is:

```bash
cd frontend
npm run build
```

Validation result in this workspace on March 29, 2026:

- `npm run build` succeeded

### Packaging validation

```bash
uv build
```

Validation result in this workspace on March 29, 2026:

- source distribution build succeeded
- wheel build succeeded

## Repository Layout

```text
.
|-- alembic/                  # Database migrations
|-- frontend/                 # Vite/React frontend
|-- relay/
|   |-- api/                  # FastAPI routers
|   |-- artifacts/            # Artifact storage helpers and parsers
|   |-- copilot/              # Model list, Copilot detection, prompts, sessions
|   |-- models/               # SQLAlchemy models
|   |-- realtime/             # WebSocket subscriptions and log/status streaming
|   |-- schemas/              # Pydantic request/response models
|   |-- services/             # Business-logic services
|   |-- worker/               # Scheduler, orchestrator, phase runner
|   |-- cli.py                # Typer CLI
|   |-- config.py             # Runtime settings
|   `-- db.py                 # Async database setup
|-- tests/                    # Unit, integration, and e2e tests
|-- Dockerfile
|-- docker-compose.yml
|-- pyproject.toml
`-- uv.lock
```

## Known Gaps

- There is no standalone lint command configured for either backend or frontend.
- There is no frontend unit/integration test script yet; the build is the current frontend verification step.
- Relay currently assumes GitHub Copilot CLI semantics and does not abstract execution to multiple provider CLIs.
- In this workspace, the frontend build depends on `frontend/src/lib/utils.ts`, but `.gitignore` currently ignores `frontend/src/lib/`. The local build passed here because that file exists locally; a fresh clone may need the ignore rule fixed or the file explicitly added to source control.

## License

Relay is licensed under the MIT License. See [`LICENSE`](./LICENSE).
