# Contributing to Relay

Relay accepts focused bug fixes, features, documentation, and compatibility
evidence. Open an issue before work that changes a workflow, persistence,
event, CLI, or HTTP contract.

## Prerequisites

- Git
- Python 3.10 through 3.14
- [uv](https://docs.astral.sh/uv/)
- Node.js `^20.19.0` or `>=22.12.0` and npm for frontend or package builds

Node.js is a build dependency. A wheel installation must run without it.

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
   cd ..
   ```

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

## Tests and documentation

Add focused tests for normal contributions. Use real subjects under test and
patch only external collaborators. Update the durable document that owns the
behavior, and validate commands and workflow examples against the real code.

Hand-authored documentation lives in `README.md` and `docs/*.md`. Generated
CLI help in the README is refreshed with:

```bash
uv run cog -r README.md
```

Do not edit `CHANGELOG.md` outside a release task.

## Pull requests

Keep commits narrow and reviewable. A pull request should state:

- the behavior changed,
- the checks run and their exact result,
- any platform or external-agent evidence that could not be collected,
- whether persistence or public contracts changed.

Never include credentials, private provider output, local run artifacts, or
retained worktrees in a commit.
