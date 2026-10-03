# Contributing to Relay

Relay accepts focused bug fixes, features, documentation, and compatibility
evidence. Open an issue before work that changes a workflow, persistence,
event, CLI, or HTTP contract.

## Prerequisites

- Git
- Python 3.10 through 3.14
- [uv](https://docs.astral.sh/uv/)
- Node.js `^20.19.0` or `>=22.12.0` and npm for frontend or package builds

CI uses Node.js 24.21.0. Node.js is a build dependency. A wheel installation
must run without it.

## Development setup

1. Clone your fork and enter the repository.

   ```bash
   git clone git@github.com:YOUR_NAME/relay.git
   cd relay
   ```

2. Create a feature branch.

   ```bash
   git switch -c feat/short-description
   ```

3. Install the locked Python environment and pre-commit hooks.

   ```bash
   uv sync --frozen
   uv run pre-commit install
   ```

4. Install the locked frontend dependencies when changing the web application
   or building a distribution.

   ```bash
   cd frontend
   npm ci
   npm run build
   cd ..
   ```

Editable Python installs skip the frontend build and need no Node runtime.
Before running `relay up` from a checkout, build the browser application with
the commands above. Rebuild it after changing frontend sources.

## Checks

Run the smallest check that proves each edit, then run the repository gates
before opening a pull request:

```bash
make check
make test
make build
make check-dist
```

`make test` runs the supported Python matrix through tox. Frontend and package
builds use the committed npm lockfile. Do not hand-edit generated files under
`relay/static/`; regenerate them through the frontend build.

The Markdown hook checks every supplied file. Its `--` delimiter ends the
list of disabled rules before file names. [Markdown configuration](.markdownlint.jsonc)
keeps the 80-column limit for prose and code, permits wider table rows, and
allows the changelog's literal `<Unreleased>` marker. Duplicate headings
remain allowed. Run the hook directly with:

```bash
uv run pre-commit run markdownlint --all-files
```

For a frontend-only check, run:

```bash
npm --prefix frontend run build
```

The pre-commit license gate checks runtime dependencies against the allow-list
in `pyproject.toml`. Run it directly with `uv run liccheck`. The pinned
`agent-client-protocol` 0.12.1 and `huey` 3.4.0 omit license metadata, so the
gate authorizes those exact releases based on their source licenses:
[ACP Apache-2.0](https://github.com/agentclientprotocol/python-sdk/blob/0.12.1/LICENSE)
and [Huey MIT](https://github.com/coleifer/huey/blob/3.4.0/LICENSE). Recheck the
source license before changing either authorized version.

`make check-dist` also asserts that the wheel contains compiled static assets,
the source distribution contains its frontend build inputs, and neither
distribution contains workflow or prompt templates.

## Code boundaries

- Keep workflow rules in domain and application modules.
- Keep Click, Django, Huey, ACP transport, Git subprocess, and browser code in
  their interface or adapter layers.
- Add no service dependency for the local runtime.
- Preserve Relay-owned errors at CLI, HTTP, SSE, and browser boundaries.
- Use argument vectors for Git, coding-agent, and command-node subprocesses.
- Keep Linux, Windows, and macOS behavior equivalent.

Every changed Python function and method needs accurate parameter and return
types. Every changed mutable or optional attribute needs an explicit type.
Declare instance-attribute types at class scope. Let local variables infer
their types unless the configured `ty` check needs an annotation. Django model
access uses validated repository accessors; the project does not use
`django-stubs`.

## Tests and documentation

Add focused tests for normal contributions. Use real subjects under test and
patch only external collaborators. Update the durable document that owns the
behavior, and validate commands and workflow examples against the real code.

Hand-authored documentation lives in `README.md` and `docs/*.md`. Generated
CLI help in the README is refreshed with:

```bash
uv run cog -r README.md
```

Run the applicable documentation checks before staging a documentation change:

```bash
uv run python scripts/check_doc_links.py README.md CONTRIBUTING.md docs/*.md
uv run python scripts/check_transition_docs.py
uv run python scripts/check_workflow_examples.py docs/workflows.md
```

The link check validates local targets and heading fragments. Run the transition
check after editing `state.py` or the transition tables in `docs/execution.md`.
Run the workflow-example check after editing the guide or workflow validation;
it loads and validates tagged examples against their expected outcomes without
executing their command nodes or agents.

Do not edit `CHANGELOG.md` outside a release task.

## Pull requests

Keep commits narrow and reviewable. A pull request should state:

- the behavior changed,
- the checks run and their exact result,
- any platform or external-agent evidence that could not be collected,
- whether persistence or public contracts changed.

Never include credentials, private provider output, local run artifacts, or
retained worktrees in a commit.
