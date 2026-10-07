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

Relay Phase 1 is implemented but unreleased. All five supported agents passed
authenticated writer-workflow certification on macOS arm64 on 2026-10-03.
Live provider execution on Linux and Windows remains unverified. Exact
versions, model selectors, artifact hashes, cleanup results, and remaining
verification limits are recorded in [`certification/`](certification/README.md).
The persistence, workflow, CLI, HTTP, SSE, and artifact formats become versioned
contracts at the first release.

Phase 1 is local and single-owner. It contains no remote workers, containers,
Redis, Postgres, model fallback, automatic merge, or
bundled workflow templates.
Opt-in [automatic recovery](docs/execution.md#automatic-step-recovery) retries
eligible agent failures up to twice with the same model and settings, retained
reports, and a separate repair instruction. It stops on unsafe failures or an
exhausted budget.
Configure [stage repair rules](docs/workflows.md#stage-repair-rules) to run a
selected fixer and verifier after a rejected verdict. The map keeps the main
stages; the Repairs panel shows each round, its settings, and retained reports.
Confirmed provider usage resets can resume a failed stage automatically while
preserving its captured model, effort, and prompts. Unsupported or missing reset
information remains visible for the owner. See
[Provider usage resets](docs/execution.md#provider-usage-resets).
An owner can retry a stopped agent step with another installed tool and exact
model. Relay validates the selection and keeps completed steps, prompts, and
the original snapshot. See
[Failure and recovery](docs/execution.md#failure-cancellation-and-recovery).
Use **Pause new steps** to let current work finish while holding the next
stage. Change an unstarted agent's settings, then resume explicitly; completed
work and captured instructions stay saved. See
[Pause new steps](docs/execution.md#pause-new-steps-and-change-an-unstarted-agent).

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
relay doctor
relay up
```

`relay init` creates only `.relay/workflows/workflow.yaml` and
`.relay/prompts/prompt.md`. `relay up` binds to loopback and opens the browser.
In **Workflows**, choose **New workflow**, add stages and instructions, save,
and start work. **Runs** shows progress, readable output, and requests for your
input.

Login is required by default. Use `relay up --no-login` to open the local app
without credentials. The saved `login_required` setting keeps this choice for
later starts. See [Open without a login](docs/web-ui.md#open-without-a-login).

Relay captures the exact saved workflow and instruction files for each run;
they do not need a Git commit before launch. Untouched initialization files
and supported generated planning and review documents may stay untracked.
Staged changes and unrelated edits still block launch. Commit workflow files
when you want to share them; Relay leaves owner documents unstaged and
uncommitted. See [Git and artifacts](docs/git-and-artifacts.md#clean-launch)
for the launch rules.

`relay doctor` reports all five agents and passes when its Git, database,
packaged-asset, and registry checks pass and at least one supported agent is
ready. Missing optional agents remain visible in the report. A failed core
check or no ready agent returns exit code 6.

Administration commands show readable text by default. Use `relay doctor
--json`, `relay project list --json`, `relay project relink OLD_PATH NEW_PATH
--json`, or `relay data clean --json` to keep their previous sorted JSON
output. `relay --json COMMAND` also selects that output for a nested command.
Relay errors show `Error: <message>` and, when available,
`Next: <next_action>`; `--json` keeps the previous error envelope and exit
codes. Initialization and startup keep their previous text in `--json` mode.

`relay doctor` uses the launch cleanliness checker for untouched starter files
and root reports. It lists allowed changes as a warning. Unrelated edits and
staged files still fail the check. Workflow-specific source exemptions are
validated during launch for the selected workflow; `doctor` does not select
a workflow or certify its inputs and model routes.

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
  --json         Keep the existing machine-readable output.
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
  --json       Keep the existing machine-readable output.
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
Django and Uvicorn serve HTTP and replayable server-sent events with optional
owner login.
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

Relay rejects staged changes and unrelated edits before launch. Validated
workflow sources and supported generated documents follow the
[launch rules](docs/git-and-artifacts.md#clean-launch). Relay never merges a
run branch into the launch branch.

## Development

See [CONTRIBUTING.md](CONTRIBUTING.md) for the Python and frontend setup,
focused checks, and packaging workflow.

The [Relay TODO list](docs/todo.md) records the agent configuration feature
checklist.

## Changelog

See [CHANGELOG.md](CHANGELOG.md).

## License

MIT © [Visesh Prasad](https://github.com/viseshrp)
