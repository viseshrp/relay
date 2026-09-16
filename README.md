# Relay

[![PyPI version](https://img.shields.io/pypi/v/relay-app.svg)](https://pypi.org/project/relay-app/)
[![Python versions](https://img.shields.io/pypi/pyversions/relay-app.svg?logo=python&logoColor=white)](https://pypi.org/project/relay-app/)
[![CI](https://github.com/viseshrp/relay/actions/workflows/main.yml/badge.svg)](https://github.com/viseshrp/relay/actions/workflows/main.yml)
[![Coverage](https://codecov.io/gh/viseshrp/relay/branch/main/graph/badge.svg)](https://codecov.io/gh/viseshrp/relay)
[![License: MIT](https://img.shields.io/github/license/viseshrp/relay)](https://github.com/viseshrp/relay/blob/main/LICENSE)
[![Format: Ruff](https://img.shields.io/badge/format-ruff-000000.svg)](https://docs.astral.sh/ruff/formatter/)
[![Lint: Ruff](https://img.shields.io/badge/lint-ruff-000000.svg)](https://docs.astral.sh/ruff/)
[![Typing: ty](https://img.shields.io/badge/typing-checked-blue.svg)](https://docs.astral.sh/ty/)

Relay turns coding-agent runbooks into local, durable workflows. It keeps the
workflow definition in Git, runs each attempt in an isolated worktree, and
puts authoring, launch, live output, human decisions, and recovery in one
loopback-only web application.

## Status

Relay Phase 1 is implemented but unreleased. Live certification remains
environment-dependent; the current five-agent gaps are recorded in
[`certification/`](certification/README.md). The persistence, workflow, CLI,
HTTP, SSE, and artifact formats become versioned contracts at the first
release.

Phase 1 is local and single-owner. It contains no remote workers, containers,
Redis, Postgres, automatic retries, model fallback, automatic merge, or
bundled workflow templates.

## Requirements

- Python 3.10 through 3.14
- Git
- macOS, Linux, or Windows
- At least one supported coding agent with its own credentials for agent nodes

End users do not need Node.js. Contributors who build the browser application
need a Node version supported by Vite; see [CONTRIBUTING.md](CONTRIBUTING.md).

## Installation

```bash
pip install relay-app
```

`pipx install relay-app` and `uv tool install relay-app` provide isolated CLI
installations.

## Quick start

Run these commands from a clean Git repository:

```bash
relay init
git add .relay
git commit -m "Add blank Relay workflow"
relay doctor
relay up
```

`relay init` creates only `.relay/workflows/workflow.yaml` and
`.relay/prompts/prompt.md`. `relay up` binds to loopback and opens the browser,
where workflows are edited and runs are controlled. After saving a workflow,
commit the `.relay/` change before launching it; Relay starts runs only from a
clean Git snapshot.

## Command reference

<!-- [[[cog
import cog
from click.testing import CliRunner

from relay.cli import main

commands = (
    (["--help"], "$ relay --help"),
    (["data", "clean", "--help"], "$ relay data clean --help"),
)
for index, (arguments, prompt) in enumerate(commands):
    result = CliRunner().invoke(main, arguments, prog_name="relay")
    if result.exit_code != 0:
        raise RuntimeError(result.output) from result.exception
    if index:
        cog.outl()
    cog.outl("```console")
    cog.outl(prompt)
    cog.out(result.output)
    cog.outl("```")
]]] -->
```console
$ relay --help
Usage: relay [OPTIONS] COMMAND [ARGS]...

  Run Relay setup and local administration commands.

  Workflow authoring and run control are available in the browser started by
  `relay up`.

Options:
  -v, --version  Show the version and exit.
  -h, --help     Show this message and exit.

Commands:
  data     Inspect or delete retained local Relay data.
  doctor   Check local storage, assets, Git, and coding-agent readiness.
  init     Create a blank .relay project surface in the current Git...
  project  Inspect or relink registered projects.
  up       Start the loopback web application and local worker.
```

```console
$ relay data clean --help
Usage: relay data clean [OPTIONS]

  Delete confirmed local run data and retained Git state.

Options:
  --runs       Delete run records, snapshots, and artifacts.
  --worktrees  Remove preserved run worktrees.
  --branches   Delete retained run and attempt refs.
  --all        Select every category, including logs.
  -h, --help   Show this message and exit.
```
<!-- [[[end]]] -->

The CLI handles setup and administration. Workflow launch, permissions,
elicitations, waits, cancellation, resume, rerun, history, artifacts, and
cleanup are browser actions.

## Architecture

Relay owns workflow state in SQLite. Huey dispatches eligible attempts, while
Django and Uvicorn serve authenticated HTTP and replayable server-sent events.
React Flow and a synchronized YAML editor provide the browser authoring
surface. Coding agents run through Agent Client Protocol adapters, except for
Antigravity's documented native headless interface.

Project files stay under `.relay/`. Mutable state, snapshots, logs, retained
artifacts, and worktrees use operating-system-specific user directories.

## Privacy and safety

Relay binds to loopback, emits no product telemetry, and stores owner-visible
run history until explicit deletion. Agent and command processes inherit the
worker environment. Relay does not mask environment values or manage agent
credentials, so prompts, output, logs, and commands may contain sensitive
data.

Relay refuses to launch from a dirty repository. It never merges a run branch
into the launch branch.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the Python and frontend setup,
focused checks, and packaging workflow.

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## License

MIT © [Visesh Prasad](https://github.com/viseshrp)
