# Codex Implementation Prompt

## Context

You are implementing a web application called **Relay** — a self-hostable AI workflow orchestration app that chains GitHub Copilot CLI sessions through a multi-phase coding workflow.

There are two reference documents in this repo that together form your complete specification:

1. **`PRODUCT_SPEC.md`** — The full product specification. This is the source of truth for what to build. Every behavior, status, state transition, API endpoint, database schema, artifact layout, and UI page is defined here. Do not deviate from it.

2. **`IMPLEMENTATION_PLAN.md`** — The implementation plan. This defines the project structure (every file and module), build phases, and testing strategy. Follow the file/module structure exactly as specified.

Read both documents in full before writing any code.

## What to Build

Implement the entire application end-to-end following the implementation plan's project structure and phase ordering. Build all 7 phases. The output should be a complete, runnable application.

## Critical Constraints

### Follow the spec exactly
- The database schema in `PRODUCT_SPEC.md` Section 12 is the source of truth for all ORM models.
- The API surface in Section 14 is the source of truth for all endpoints, request/response shapes, and URL paths.
- The WebSocket event model in Section 15 is the source of truth for all real-time messages.
- The workflow state machine in Section 6 is the source of truth for all status transitions. Implement these as explicit guard functions, not ad-hoc conditionals scattered across the codebase.
- The artifact layout in Section 13 is the source of truth for all file paths.

### Follow the project structure exactly
- The file tree in `IMPLEMENTATION_PLAN.md` is the target structure. Create every file listed. Do not invent additional files or merge files together.
- Module responsibilities are defined per-file in the plan. Respect the boundaries.

### Technology decisions (locked in)
- **Backend:** Python 3.12, FastAPI, SQLAlchemy (async, aiosqlite), Alembic, Pydantic v2
- **Frontend:** React 18, TypeScript, Vite, Tailwind CSS, shadcn/ui, Zustand, @tanstack/react-query, react-router-dom v6, lucide-react, react-markdown
- **CLI:** typer
- **Database:** SQLite with WAL mode
- **Docker:** Multi-stage build (Node for frontend, Python for backend), `gh` CLI + Copilot extension pre-installed in image

### Dependency versions
Pin to these in pyproject.toml:
```
fastapi >= 0.115
uvicorn >= 0.34
sqlalchemy >= 2.0
aiosqlite >= 0.20
alembic >= 1.14
pydantic >= 2.10
typer >= 0.15
psutil >= 6.1
websockets >= 14.0
```

Pin to these in package.json:
```
react: ^18.3
react-dom: ^18.3
react-router-dom: ^6.28
@tanstack/react-query: ^5.62
zustand: ^5.0
tailwindcss: ^3.4
lucide-react: ^0.468
react-markdown: ^9.0
```
Use `npx shadcn@latest init` defaults, then add these shadcn/ui components: `button`, `input`, `textarea`, `select`, `dialog`, `sheet`, `tabs`, `badge`, `card`, `table`, `dropdown-menu`, `toggle`, `separator`, `scroll-area`, `tooltip`, `skeleton`, `alert`.

### Known Copilot Models List
Create `relay/copilot/models.py` with this hardcoded list:
```python
KNOWN_MODELS = [
    {"id": "gpt-4o", "name": "GPT-4o", "provider": "openai"},
    {"id": "gpt-4.1", "name": "GPT-4.1", "provider": "openai"},
    {"id": "gpt-4.1-mini", "name": "GPT-4.1 Mini", "provider": "openai"},
    {"id": "gpt-4.1-nano", "name": "GPT-4.1 Nano", "provider": "openai"},
    {"id": "claude-sonnet-4", "name": "Claude Sonnet 4", "provider": "anthropic"},
    {"id": "claude-3.5-sonnet", "name": "Claude 3.5 Sonnet", "provider": "anthropic"},
    {"id": "gemini-2.0-flash", "name": "Gemini 2.0 Flash", "provider": "google"},
    {"id": "o3-mini", "name": "o3-mini", "provider": "openai"},
]

DEFAULT_MODEL = ""  # Empty string = use Copilot CLI default
```

### Exploration Message Flow (Detailed)
The Exploration phase has a unique server↔worker interaction pattern:

1. User sends a message via `POST /runs/{run_id}/exploration/messages`.
2. API handler saves the message to `exploration_messages` table with `role='user'`.
3. The worker's Exploration phase runner polls `exploration_messages` for new user messages (messages with `sequence_number` > last processed).
4. Worker sends the message to the Copilot CLI subprocess stdin.
5. Worker reads streaming stdout chunks and writes them to a JSONL streaming file: `<relay-data-dir>/logs/<run-id>/exploration_stream.jsonl`. Each line: `{"message_id": "uuid", "content": "chunk", "done": false}`.
6. Server tails this JSONL file and emits `exploration_chunk` WebSocket events.
7. When the Copilot response is complete, worker writes a final `{"message_id": "...", "content": "", "done": true}` line, then saves the full assistant message to `exploration_messages`.
8. On finalize (`POST /runs/{run_id}/exploration/finalize`): API sets a `finalize_requested` boolean column on the `workflow_runs` row. Worker detects this, sends the finalization prompt to generate the planning prompt artifact, saves it, marks Exploration phase as succeeded.

Add `finalize_requested` (BOOLEAN DEFAULT FALSE) and `head_commit` (TEXT NULL) columns to the `workflow_runs` table beyond what the spec lists. These are implementation details the spec didn't need to surface.

### Prompt Templates
Write complete, production-quality prompt templates in `relay/copilot/prompts.py`. Each prompt should be a Python function that takes the required inputs and returns a string. The prompts must:

- **Exploration finalization prompt:** Instruct the model to summarize the conversation into a structured Markdown document with sections: Problem, Goals, Constraints, Preferred Stack, Files to Read, Desired Output. Include the selected context paths.
- **Planning prompt:** Include the full planning_prompt.md content and context paths. Instruct the model to create SPEC.md and IMPLEMENTATION_PLAN.md in the `.relay/<run-id>/planning/` directory. Be explicit about the output directory path.
- **Critique prompt:** Include SPEC.md and IMPLEMENTATION_PLAN.md content inline. Instruct the model to produce IMPLEMENTATION_PLAN_CRITIQUED.md using `> **Critique:** ...` blockquotes for human-readable comments and `<!-- CRITIQUE: ... -->` HTML comments for machine parsing. Specify output path.
- **Correction prompt:** Include the critiqued plan. Instruct the model to address all critique points and produce a clean corrected IMPLEMENTATION_PLAN.md. Specify output path.
- **Execution prompt:** Include SPEC.md and corrected IMPLEMENTATION_PLAN.md. Instruct the model to implement the plan, then run build/test/lint validation. Be explicit that changes should be made in the working tree, not committed.
- **Review prompt:** Include SPEC.md and corrected IMPLEMENTATION_PLAN.md. Instruct the model to review the implementation and produce two files: REVIEW_COMMENTS.json (array of `{file, line, severity, comment}` objects inside a ` ```relay-review-comments ``` ` fenced block in stdout) and REVIEW_SUMMARY.md following the template (Summary, Deviations from Spec, Risks, Suggestions, Verdict). Verdict must be exactly one of: PASS, FAIL, PASS_WITH_WARNINGS.
- **Fix prompt:** Include review findings (REVIEW_COMMENTS.json + REVIEW_SUMMARY.md), SPEC.md, and corrected IMPLEMENTATION_PLAN.md. Instruct the model to fix the identified issues and re-run validation.

Every prompt must include the full list of context paths selected during Exploration.

### shadcn/ui Component Mapping
Use these shadcn/ui components for the corresponding UI elements:

| UI Element | shadcn Component |
|-----------|-----------------|
| Navbar navigation links | Custom with `Button` variant="ghost" |
| Autopilot toggle | `Toggle` |
| Status badges | `Badge` with variant per status color |
| Project cards | `Card` |
| Data tables (runs, comments) | `Table` |
| Phase detail tabs | `Tabs` |
| Confirmation dialogs (cancel, delete) | `Dialog` |
| Fix prompt editor | `Sheet` (slide-in from right) with `Textarea` |
| Context panel (file tree) | `Sheet` (slide-in from right) with `ScrollArea` |
| Model selection dropdowns | `Select` |
| Settings form inputs | `Input`, `Select`, `Toggle` |
| Log viewer container | `ScrollArea` with monospace styling |
| Loading states | `Skeleton` |
| Copilot CLI missing warning | `Alert` |
| Phase graph nodes | Custom div with `Badge` for status, not a shadcn component |
| Workflow action buttons | `Button` (primary/destructive variants) |

### Async File Tailing Pattern
For `relay/realtime/log_tailer.py`, use this pattern:
```python
import asyncio
import aiofiles

async def tail_file(path: str):
    """Async generator that yields new lines as they are appended to a file."""
    async with aiofiles.open(path, mode='r') as f:
        # Seek to end
        await f.seek(0, 2)
        while True:
            line = await f.readline()
            if line:
                yield line
            else:
                await asyncio.sleep(0.1)
```
Add `aiofiles >= 24.1` to pyproject.toml dependencies.

### Docker Setup
```dockerfile
# Stage 1: Frontend build
FROM node:20-slim AS frontend
WORKDIR /app/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# Stage 2: Backend
FROM python:3.12-slim
WORKDIR /app

# Install gh CLI
RUN apt-get update && \
    apt-get install -y curl git && \
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg && \
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null && \
    apt-get update && \
    apt-get install -y gh && \
    rm -rf /var/lib/apt/lists/*

# Install Copilot extension
RUN gh extension install github/gh-copilot

# Install uv and Python deps
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

# Copy app code
COPY relay/ ./relay/
COPY alembic/ ./alembic/
COPY alembic.ini ./

# Copy frontend build
COPY --from=frontend /app/frontend/dist ./frontend/dist

EXPOSE 8080
ENTRYPOINT ["uv", "run", "relay"]
CMD ["dev"]
```

docker-compose.yml for production use:
```yaml
services:
  relay:
    build: .
    ports:
      - "8080:8080"
    volumes:
      - relay-data:/data
      - ${HOME}/.config/gh:/root/.config/gh:ro  # GH auth credentials
      - /path/to/projects:/projects              # User's project folders
    environment:
      - RELAY_DATA_DIR=/data
      - RELAY_HOST=0.0.0.0
      - RELAY_PORT=8080
    command: ["dev"]

volumes:
  relay-data:
```

### CopilotSession Implementation Guidance
For `relay/copilot/session.py`:

- Use `asyncio.create_subprocess_exec` (not `subprocess.Popen`) for native async I/O.
- For streaming stdout: read with `process.stdout.readline()` in an async loop.
- For stdin writes (sending prompts): use `process.stdin.write()` + `process.stdin.drain()`.
- Session reuse: keep the process handle alive. To send a follow-up, write to stdin again. If `process.returncode is not None`, the session has exited — start a new one (degraded fallback).
- Kill: `process.kill()` then `await process.wait()`.
- The `CopilotSession` interface:

```python
class CopilotSession:
    async def start(self, cmd: list[str], cwd: str, env: dict | None = None) -> None: ...
    async def send(self, prompt: str) -> AsyncIterator[str]: ...  # yields stdout chunks
    async def send_followup(self, prompt: str) -> AsyncIterator[str]: ...  # reuse session
    def is_alive(self) -> bool: ...
    async def kill(self) -> None: ...
    async def wait(self) -> int: ...  # returns exit code
    @property
    def pid(self) -> int | None: ...
```

### FakeCopilotSession for Testing
`tests/mocks/fake_copilot.py` should implement the same interface as `CopilotSession` but:
- Accept a list of canned responses (strings) at construction time.
- `send()` yields the next canned response, character by character with a configurable delay (default 0.01s per chunk of ~20 chars).
- Accept a `fail_on_attempt` parameter: list of attempt numbers that should simulate a crash (raise exception or return non-zero exit code).
- `is_alive()` returns True until all canned responses are consumed or a failure is triggered.

### Worker Main Loop Pattern
```python
async def run_worker():
    scheduler = Scheduler()
    monitor = ProcessMonitor()

    # On startup: recover orphaned phases
    await monitor.recover_orphans(db)

    while True:
        # Check for cancellation requests
        await handle_cancellations(db)

        # Check for user actions (advance, rerun, fix)
        await handle_user_actions(db)

        # Pick up new work if capacity available
        if scheduler.has_capacity():
            workflow = await pick_next_queued_workflow(db)
            if workflow:
                asyncio.create_task(run_workflow(workflow))

        # Health check active processes
        await monitor.check_health()

        await asyncio.sleep(1.0)
```

Each `run_workflow` is an async task that drives one workflow through its phases sequentially. The worker's main loop manages concurrency by tracking how many `run_workflow` tasks are active.

## What NOT to Do

- Do not add authentication/authorization.
- Do not add features not in the spec.
- Do not create README.md or other documentation files (except inline code comments where non-obvious).
- Do not add extra API endpoints beyond what Section 14 specifies.
- Do not use emoji in code or comments.
- Do not add type stubs, excessive docstrings, or boilerplate comments.
- Do not create a separate abstraction layer for "future Cursor CLI support." Build for Copilot CLI directly.

## Build Order

Follow the MVP rollout order from `IMPLEMENTATION_PLAN.md` exactly (steps 1-15). Each step should produce working, testable code before moving to the next. Write tests alongside the code they cover, not as a separate final phase.

## Final Verification

After implementation is complete, verify:
1. `uv run relay dev` starts both server and worker
2. `docker build .` succeeds
3. `uv run pytest` passes all tests
4. Frontend builds with `cd frontend && npm run build`
5. The full autopilot workflow (project create -> workflow -> Exploration -> auto-complete) works end-to-end with FakeCopilotSession
