# Working on Relay

Relay turns coding-agent runbooks into durable workflows in a local,
single-owner web application. Python owns execution and persistence; the React
application provides workflow authoring, monitoring, and owner controls.
Use this guide for repository changes. Product behavior belongs in the linked
documentation and its implementation.

## Start each task

1. Read [README.md](README.md), [CONTRIBUTING.md](CONTRIBUTING.md), and the
   documentation for the area being changed. Check for additional instructions
   in that directory. Honor the task's scope, phase, approval gates, and exact
   output requirements.
2. Inspect `git status --short --branch`, `git diff`, and `git diff --cached`.
   Preserve existing edits and untracked planning or review documents, including
   `DRAFT_PLAN.md`, `REVIEW.md`, and `WALKTHROUGH.md`. Never stage, delete, rewrite,
   or ignore them to make the checkout appear clean.
3. Use `rg` and `rg --files` to locate the implementation and nearby tests.
   Trace behavior through its service, persistence adapter, API, and frontend
   when the change crosses those boundaries. Keep the patch within the request.
4. Make the change and run checks appropriate to its behavior. Use disposable
   repositories and isolated storage for execution tests. Keep automated tests
   independent of installed provider accounts and owner data.
5. Review the final diff and Git status. Report the behavior changed, checks and
   results, and any remaining limitation. Commit, push, merge, tag, or publish
   only within authorization already provided by the user or task contract.

Continue an assigned branch. Use `feat/` for a new branch unless instructed
otherwise. Stage explicit paths when a commit is authorized; avoid `git add -A`
in a checkout with unrelated work. Do not reset or stash owner changes.

## Find the owning code and documentation

| Area | Implementation | Behavior reference |
| --- | --- | --- |
| Workflow parsing, validation, graphs, prompts, outputs, snapshots | [relay/workflows/](relay/workflows/) | [docs/workflows.md](docs/workflows.md) |
| Scheduling, dispatch, node execution, controls, recovery | [relay/execution/](relay/execution/) | [docs/execution.md](docs/execution.md) |
| Provider discovery, models, configuration, ACP and native transports | [relay/agents/](relay/agents/) | [docs/agents.md](docs/agents.md), [certification/](certification/README.md) |
| Git cleanliness, worktrees, commits, retained evidence | [relay/vcs/](relay/vcs/) | [docs/git-and-artifacts.md](docs/git-and-artifacts.md) |
| Project identity, settings, paths, durable storage | [relay/projects/](relay/projects/), [config.py](relay/config.py), [paths.py](relay/paths.py), [models.py](relay/web/models.py), [repositories.py](relay/web/repositories.py) | [docs/projects-and-storage.md](docs/projects-and-storage.md) |
| CLI, HTTP, authentication, SSE, supervision | [cli.py](relay/cli.py), [relay/web/](relay/web/) | [docs/http-api.md](docs/http-api.md), [docs/web-ui.md](docs/web-ui.md) |
| Browser authoring, run views, API types | [frontend/src/](frontend/src/) | [docs/web-ui.md](docs/web-ui.md) |
| Packaging and repository gates | [hatch_build.py](hatch_build.py), [scripts/](scripts/), [Makefile](Makefile), [pyproject.toml](pyproject.toml) | [docs/packaging.md](docs/packaging.md), [CONTRIBUTING.md](CONTRIBUTING.md) |

Python tests live in [tests/](tests/); browser tests live in
[frontend/e2e/](frontend/e2e/). Reuse the fixtures in
[tests/conftest.py](tests/conftest.py), helpers in
[tests/support.py](tests/support.py), deterministic providers in
[tests/fake_agent.py](tests/fake_agent.py), and isolated browser server in
[tests/e2e_server.py](tests/e2e_server.py).

## Set up the checkout

Python supports 3.10 through 3.14. Use the locked uv environment:

```bash
uv sync --frozen
uv run pre-commit install
```

Frontend work and distribution builds require npm and Node compatible with
[frontend/package.json](frontend/package.json). Install locked dependencies and
build the application before serving it from an editable checkout:

```bash
npm --prefix frontend ci
npm --prefix frontend run build
```

Editable Python installation skips the frontend build. Rebuild after frontend
changes. Installed wheels must serve their compiled assets without Node or npm
at runtime. Follow [docs/packaging.md](docs/packaging.md) for that smoke check.

## Preserve the runtime contracts

These rules describe Relay's implementation. A requested change to a contract
must include its persistence, API, frontend, documentation, and test effects as
applicable; do not silently change adjacent behavior.

### Local product and layer boundaries

- Phase 1 stays local and single-owner. Add no remote workers, required service,
  container runtime, Redis, Postgres, automatic merge, or bundled workflow and
  prompt templates without an explicit product request.
- Keep workflow and execution rules in Python services. Click, Django views,
  Huey, provider transports, and Git subprocesses adapt those rules to their
  interfaces. Keep Django persistence in the repository adapters.
- Keep portable workflow sources under `.relay/`; mutable databases, logs,
  artifacts, resources, and worktrees belong in platform-specific user storage.
  Resolve paths through the existing configuration and path helpers.
- Keep the CLI focused on setup and administration. Workflow authoring, launch,
  run controls, and history belong in the browser and HTTP services.
- Keep macOS, Linux, and Windows behavior equivalent. Use the existing path and
  process adapters rather than assuming POSIX paths, signals, or executables.

### Durable execution and recovery

- `relay.db` is authoritative. Huey's separate `huey.db` carries opaque claim
  tokens. Commit dispatch intent before enqueueing; atomically claim admission
  and create one attempt. Duplicate delivery must not create another attempt.
- Keep state transitions and their events in one transaction. Use
  [state.py](relay/execution/state.py) and [machine.py](relay/execution/machine.py)
  rather than ad hoc status assignments. Keep transactions short; run Git,
  network operations, and filesystem cleanup outside them.
- Keep `run_node_attempt` at `retries=0`. Reconciliation repairs unstarted
  delivery. Attempt recovery requires an owner retry, an enabled bounded
  recovery policy, or structured confirmation of a future provider usage reset.
  Prose and cached usage observations never authorize quota recovery. Keep
  repair instructions separate from frozen prompts, preserve rejected reports,
  and never reset the per-step automatic retry budget during restart or retry.
- Preserve immutable launch snapshots, ordered prompt bytes, typed inputs, and
  frozen routes. An explicit retry-effort change is recorded separately; it
  must preserve the model, permissions, prompts, and completed upstream work.
- Preserve fail-fast, owner cancellation, orderly interruption, and worker-loss
  distinctions. Controls and interactions belong to the current attempt and
  live session. Duplicate, stale, or expired answers must not affect another
  attempt. A declared human wait remains an owner decision.

### Git isolation and retained evidence

- Never check out, reset, or merge the launch branch as part of a run. Writers
  use the primary run worktree exclusively; readers use detached worktrees at
  the recorded committed head. Remove reader worktrees before releasing their
  admission locks.
- Runtime writing nodes commit their own changes, leave the index and code
  clean, and advance from the attempt's starting head. Only an explicit
  `allow_no_commit: true` permits a valid no-op. These runtime rules do not
  authorize repository commits outside the current task.
- Preserve the exact report and workflow-source exemptions in
  [cleanliness.py](relay/vcs/cleanliness.py). Validated launch sources and exempt
  root reports may remain unstaged or untracked. Unrelated edits and staged
  reports still block launch or writer completion. Read-only nodes fail on any
  worktree modification. Do not broaden exemptions to hide an error.
- Preserve refs, commits, diffs, untracked bytes, declared artifacts, and their
  hashes before reset or worktree removal. Preservation failure blocks those
  operations. Cleanup must retain the latest successful writer's protected head
  and must never overwrite existing evidence.
- `exists` returns a boolean and does not require or retain a report. Use
  `label`, `json_path`, or `yaml_path` for a required retained handoff. A
  successful agent turn alone does not prove that its requested work is done.

### Provider models, configuration, and permissions

- Treat model values as exact and case-sensitive. Labels, aliases, cached
  observations, and substring matches do not prove availability. Require fresh
  provider selection proof at launch and execution; reject model drift.
- Codex, Claude Code, GitHub Copilot CLI, and Cursor CLI use ACP. Antigravity
  uses its documented native headless interface. Keep that distinction in
  discovery, configuration, execution, and certification.
- Read ACP effort and permission choices dynamically for the selected model.
  Preserve provider values, labels, descriptions, and ordering. Provider default
  means an unset override. Antigravity's permission choices are adapter-defined;
  its effort must agree with its exact model slug.
- Reject unsupported explicit overrides. Never switch models, lower effort,
  change providers, or enable auto-approval to bypass a failure. Relay discovers
  existing agent installations; provider installation and authentication remain
  owner responsibilities.
- Preserve bounded initialization, prompt execution, feedback, cancellation,
  and shutdown. Keep permission answers attached to their exact request and
  session. Drop provider-private content from public events and retain ordered
  message and attempt boundaries when splitting output.

### HTTP, filesystem, and process safety

- Bind to loopback. Login is required by default, with the documented explicit
  no-login mode. Preserve CSRF protections for POST requests in both modes;
  respect the saved login choice and retain the owner's account and data.
- Use [RelayError](relay/errors.py) envelopes across CLI, HTTP, and events.
  Preserve error codes and context. Public responses omit third-party traces and
  private provider fields; diagnostic logs retain the underlying failure.
- Resolve workflow keys, prompts, static assets, and artifacts under their
  allowed roots, including symlink and platform case behavior. Preserve strict
  schema validation, safe expressions, and request, event, and resource bounds.
- Launch Git, agent, and command subprocesses with argument vectors and
  `shell=False`. Preserve process-group or Windows Job Object ownership,
  bounded shutdown, and OS creation-identity checks before stopping saved PIDs.
- Delete only resources whose paths and ownership markers are verified. Keep
  owner browser profiles, credentials, unrelated processes, and unmarked files
  outside cleanup. Use explicit confirmed cleanup for retained run data.

## Implementation and dependency standards

- Write Python compatible with 3.10. Changed functions and methods need accurate
  parameter and return types; mutable or optional attributes need explicit
  types, with instance attributes declared at class scope. Let local variables
  infer types unless `ty` requires an annotation. Use validated Django accessors;
  this project does not use `django-stubs`.
- Use the existing React, TypeScript, MUI, React Flow, and CodeMirror patterns.
  Keep [frontend/src/types.ts](frontend/src/types.ts) and
  [frontend/src/api.ts](frontend/src/api.ts) aligned with backend payloads.
  Preserve graph/YAML round trips and server validation.
  Edit `frontend/` sources; regenerate ignored `relay/static/` assets.
- Add focused regression tests for behavior changes. Exercise the real subject
  and patch external collaborators. Test failure or recovery paths when they
  are affected. Documentation-only changes need documentation checks rather
  than new behavior tests.
- Keep dependency changes within scope. Update `uv.lock` or
  `frontend/package-lock.json` through their package manager when needed. Check
  the license allow-list and reverify source licenses for pinned exceptions.
  ACP SDK or provider adapter upgrades require protocol and certification review.
- Add migrations under [relay/web/migrations/](relay/web/migrations/) when
  persistence changes. Preserve existing migration history and retained owner
  state; do not replace migrations or reset a database to pass a test.

## Validate the changed behavior

Run the smallest relevant check first, then the broader gates required by the
change and task contract. Commands below run from the repository root.

| Change or gate | Command |
| --- | --- |
| Focused Python behavior, using the relevant test file | `uv run pytest tests/test_execution_core.py -q` (example) |
| Python suite on the active interpreter | `uv run pytest tests -q` |
| Supported Python matrix via tox | `make test` |
| Lockfile and repository quality gates | `make check` |
| Frontend types and compiled assets | `npm --prefix frontend run build` |
| Browser behavior, including login and no-login configurations | `make test-frontend` |
| Distribution build and content validation | `make build`, followed by `make check-dist` |

Install Chromium once when browser tests need it:

```bash
npm --prefix frontend exec playwright install chromium
```

`make check` includes hooks that can rewrite files, including Ruff and generated
README help. Review the resulting diff. `make build` invokes `clean` and removes
build and coverage outputs before rebuilding. Packaging checks require compiled
wheel assets and frontend source-distribution inputs, and reject templates and
certification data.

Browser tests use temporary Git and storage roots plus deterministic provider
processes. Do not substitute the owner's running Relay instance or provider
credentials. Reserve authenticated provider runs for requested live validation
or certification; record exact versions, model values, platform, artifact
hashes, and cleanup results in `certification/`.

Report the checks actually run. A local interpreter pass does not establish
the full OS/Python matrix, and offline tests do not certify live providers.
Record unavailable checks and their concrete blocker without weakening a gate.

## Keep documentation in sync

Update the behavior reference from the code map when its contract changes.
Refresh generated README CLI help with `uv run cog -r README.md`; do not edit
that generated block by hand. Leave `CHANGELOG.md` for release tasks.

Markdown prose and code blocks use an 80-column limit; table rows may be wider.
For a documentation-only change, run file-scoped hooks and local-link checks.
For this file:

```bash
uv run pre-commit run --files AGENTS.md
uv run python scripts/check_doc_links.py AGENTS.md
```

For changes to product documentation, use the applicable checks:

```bash
uv run python scripts/check_doc_links.py \
  README.md CONTRIBUTING.md docs/*.md
uv run python scripts/check_transition_docs.py
uv run python scripts/check_workflow_examples.py docs/workflows.md
```

The transition check applies to state-machine and transition-table changes.
The workflow-example check applies to workflow validation and tagged guide
examples; it validates without executing their agents or commands.

## Communicate with the owner

When the agent runtime provides `no-ai-slop` and `i-have-adhd`, load and apply
both before user-facing prose. Apply them silently. Keep these standards across
agents that do not have the skills installed:

- Lead with the answer, outcome, or next action. Use plain language and preserve
  technical details, exact commands, filenames, caveats, and evidence.
- Number multi-step work and keep each step bounded. Keep progress updates
  brief, restate useful task state, and make completed work visible.
- Apply ADHD-friendly structure until the owner requests `stop adhd mode` or
  `normal mode`. For factual or analytical requests, lead with the conclusion
  rather than inventing a next task.
- Ask only for missing decisions or authorization that the task does not already
  provide. Continue independent work while clarification is pending. Preserve
  explicit human gates and exact-command contracts.
- End with the result, validation, and any concrete remaining blocker. Omit
  generic praise, tangents, unnecessary recaps, and a `What changed` section
  unless the owner asks for an edit. Never expose credentials or private run
  output in reports or commits.
