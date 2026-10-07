# Projects and storage

Relay keeps portable workflow definitions in the repository and mutable run
state in the owner's operating-system directories. Moving a repository does
not silently change its identity.

## Project surface

Run `relay init` inside a Git worktree. Relay creates this surface at the
worktree root:

```text
.relay/
├── prompts/
│   └── prompt.md
└── workflows/
    └── workflow.yaml
```

`workflow.yaml` contains the schema version, a name, and an empty node map.
`prompt.md` is empty. Relay does not copy workflow steps, prompt text, or other
templates. A second `relay init` leaves the directory unchanged and exits with
status 2. Running outside Git exits with status 3.
`relay up` creates this blank surface when no project is found, so the first
start needs no separate initialization command. It preserves an existing
project and uses the nearest `.relay` directory as before.
The untouched, untracked starter files do not block the first launch of a newly
created workflow. Relay leaves them in place and never stages or commits them.
Edited unused starter files and staged files still require the owner to resolve
their Git changes before launch.

From a subdirectory, Relay walks upward to the nearest `.relay/` directory but
never above the containing Git worktree.

## Central paths

Relay 1.0 uses `platformdirs` 4.11.8 with app name `relay`, no app author, and
non-roaming Windows storage. Default roots are:

| Operating system | Config | Data | Logs |
| --- | --- | --- | --- |
| macOS | `~/Library/Application Support/relay` | `~/Library/Application Support/relay` | `~/Library/Logs/relay` |
| Linux | `${XDG_CONFIG_HOME:-~/.config}/relay` | `${XDG_DATA_HOME:-~/.local/share}/relay` | `${XDG_STATE_HOME:-~/.local/state}/relay/log` |
| Windows | `%LOCALAPPDATA%\relay` | `%LOCALAPPDATA%\relay` | `%LOCALAPPDATA%\relay\Logs` |

Relay creates these directories only when needed. POSIX directories use mode
`0700`. Windows uses the account's inherited ACLs; review that directory's ACL
if other local accounts can access the profile.

The config root contains `settings.json` and `prompts/`. The data root contains
`relay.db`, `huey.db`, `artifacts/`, `worktrees/`, `resources/`, and `registry-cache/`.
It also contains `supervisor.lock` and `supervisor-processes.json`, the kernel
lease and atomic process ownership record used for
[restart after a lost supervisor](execution.md#restart-after-a-lost-supervisor).
Snapshots are database rows. Each process that emits a diagnostic, including
a CLI command, writes a rotating `relay-{pid}.log` with up to three backups
of 5 MB each. Quiet commands create no empty log file. Every log file Relay
creates starts with the line `Relay process log`, and a rotation keeps that
line. Retention and data cleanup change only `relay-{pid}.log` files and
rotations that start with it, so other files in the same directory are never
removed or emptied. Logging setup removes stopped-process files that hold only
that line and retains the three most recent stopped-process log sets that have
records, including their rotations. Files for live or unverifiable PIDs are
retained; a reused PID can therefore keep an older set until that process
exits. Files without the line, such as the former shared `relay.log` or logs
from earlier builds, are left for manual cleanup. The
[2026-10-03 Windows CI run](https://github.com/viseshrp/relay/actions/runs/37129432298)
verified retention with a live process, a stopped process, and foreign files
on Python 3.10 through 3.14.
A `RELAY_LOG_PATH=/path/custom.log` override produces
`/path/custom-{pid}.log` and its rotations. A shared override directory is
safe because Relay changes only the files it marked. Separate files prevent
concurrent processes from rotating the same open file. Diagnostic context
such as run, attempt, path, and cursor appears as escaped JSON alongside the
message and exception trace.

## Owner settings

`settings.json` is a JSON object in the config root listed above. Missing keys
use defaults; unknown keys and invalid types fail with `config_error`.
For example, this file opens the loopback app without owner credentials:

```json
{
  "login_required": false
}
```

`login_required` must be a JSON boolean and defaults to `true`. Restart Relay
after changing it. An explicit `relay up --login` or `relay up --no-login`
overrides the saved value for that process. Disabling login preserves the
owner account and all run data. See [Open without a login](web-ui.md#open-without-a-login)
for the access boundary and browser protections.

The supervisor passes its resolved choice to both children through
`RELAY_LOGIN_REQUIRED=true` or `RELAY_LOGIN_REQUIRED=false`. Direct ASGI
launches can use the same override; other values are rejected. Without it,
the web settings read `login_required` from the saved file.

## Database and disk roles

`relay.db` is the durable source for projects, drafts, editor leases, runs,
snapshots, scoped nodes, attempts, dispatch claims, events, artifacts,
interactions, control requests, agent observations, and run locks. SQLite uses
foreign keys, WAL mode, and a five-second busy timeout. Transactions use
`IMMEDIATE` mode to reserve the write lock before reading. Competing writers
wait for that reservation for up to five seconds; contention beyond that limit
becomes a Relay persistence error. Transactions contain short database changes;
Git subprocesses, network requests, and worktree cleanup run outside them.
This follows [Django's SQLite transaction guidance](https://docs.djangoproject.com/en/5.2/ref/databases/#transactions-behavior).
The Django SQLite `OPTIONS.init_command` applies WAL, foreign keys, and the
busy timeout to each connection.

The installation's Django secret key is written and flushed in a temporary
file, then published through an atomic link that cannot overwrite another
process's complete key. An incomplete or unreadable key returns a Relay
persistence error without a polling retry loop.

Snapshot text and event payloads stay in the database. Large artifact and diff
bytes live under `artifacts/`; database rows store their retained paths,
SHA-256 hashes, sizes, and preservation state. Huey's separate `huey.db` is a
dispatch adapter and never replaces committed intent in `relay.db`.

Migrations run before the web and worker children start. A kernel-backed lock
serializes migration processes for at most 15 seconds. The operating system
releases the lock if its process exits, so stale metadata in the lock file
cannot block a later start.

## Project identity and relinking

Relay resolves symlinks and normalizes path case where the operating system is
case-insensitive. For example, Windows paths `C:\Code\Relay` and
`c:\code\relay` resolve to the same canonical identity. POSIX case remains
unchanged.

List known projects with:

```bash
relay project list
```

After moving a repository, record the move explicitly:

```bash
relay project relink OLD_PATH NEW_PATH
```

`NEW_PATH` must exist inside a Git worktree. Relay rejects an unknown old path,
an already registered destination, or two paths that resolve to the same
location. Successful relinks append an audit row with both canonical paths and
the timestamp.

Each web process resolves and registers the single served project once.
Later API reads reuse that identity without invoking Git or updating
`last_opened_at` on every request.

The browser project chooser can open another registered repository or
initialize a blank `.relay` surface in a local Git worktree. Selected-project
requests identify that project explicitly; selection does not replace the
served default or another browser's project. Before an attempt starts, Relay
checks the assigned checkout's Git common directory against the registered
repository and rejects a mismatch before running the tool.

## Run-owned resources

Agent and command attempts get private scratch storage under
`resources/<run-uuid>/attempt-<random>/`. Each allocation has a versioned owner
marker naming its run, attempt, and random token. The child environment points
`TMPDIR`, `TMP`, and `TEMP` at its `temp` directory and exposes a separate
`RELAY_BROWSER_PROFILE_DIR`. Agent run metadata identifies both directories.
A tool that starts a disposable browser should use that profile directory;
Relay never redirects or deletes the owner's personal browser profile.

Completion removes only the allocation Relay created. Terminal-run cleanup
also removes marked allocations for ended attempts and can be retried from
**Settings > Storage** by selecting a completed run and confirming. The browser
loads only the selected project's succeeded, failed, and canceled runs, with
bounded pages for older runs. A replaced directory, symlinked marker, wrong run,
or mismatched token is not followed. Inner links are unlinked without deleting
their targets. Unmarked files are preserved, including during confirmed run
record deletion. Worktrees, retained evidence, provider credentials, and other
Relay runs use separate storage and remain outside temporary cleanup.

On POSIX, each command or agent runs in a new process group; Relay stops its
remaining descendants when the lifecycle ends. On Windows, a launcher joins
an unnamed Job Object before creating the target. Its non-inheritable job
handle uses `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, so surviving descendants stop
when the launcher exits. Cleanup never scans personal browser processes. A PID
saved by an earlier instance authorizes a stop only when its recorded OS
creation identity still matches; unverified older PIDs are left alone. See Microsoft's
[Job Objects documentation](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).

Files created outside the supplied temporary and profile folders remain
outside Relay's ownership. Cleanup failures are logged and reported as run
events; they do not replace a completed attempt's result.

Unexpected failures in `relay init`, `relay project list`,
`relay project relink`, or `relay data clean` show a plain error and a next
action. Add `--json` to retain the previous JSON error envelope. The local log
retains the trace. Project listings and cleanup counts also default to readable
text; their `--json` output preserves the existing fields and sorted encoding.

Static assets and retained artifact downloads use Python's built-in MIME
tables, independent of operating-system registries and MIME files.

## Retention and deletion

Run history remains until the owner confirms deletion. Each project keeps a
monotonic run counter. Deleting history never reuses a run number. Existing
runs receive numbers in snapshot creation order during migration; subsequent
runs keep their assigned number. Project rows are
protected while runs reference them. Deleting a run may cascade only through
that run's owned snapshot, nodes, attempts, events, interactions, controls,
and artifact metadata.

Evidence preservation precedes worktree removal. Relay does not delete the
only copy of a diff, artifact, or snapshot without confirmation. Retained run
branches require explicit cleanup even when a successful worktree is removed.
Cleaning run records alone is rejected while its worktree, run branch, or
retained attempt refs still exist. Clean worktrees, then Git refs, then records;
`--all` applies that order and empties Relay's marked process logs and
rotations in place, keeping each file's `Relay process log` line. Files without
that line, including the former shared `relay.log`, are left alone. Open
append handlers stay attached, so active processes can continue logging after
cleanup. The same Windows CI run verified that an open append handler writes
to the cleared file after cleanup on Python 3.10 through 3.14.

Agent and command processes inherit the worker environment. Relay has no secret
vault or output masking, so the database, artifact directory, and logs may
contain sensitive prompts, responses, command output, and tool results.

See the [README](../README.md) for installation and the local-only product
boundary.

## Global defaults and project overrides

Open **Settings** in the browser to set defaults for every registered project.
**Global defaults** saves to the installation's `settings.json`.
**Project defaults** saves only explicit overrides in the project database row.
Turn a project override off to inherit the current saved global value.
Changes apply to future launches. Existing runs retain their settings through
pause, restart, retries, loops, and child workflows.

The complete settings inventory is:

| Setting | Global control | Project or workflow override | Applies |
| --- | --- | --- | --- |
| Ordered agents | Default agent order | Project order; workflow and job `agents` come first | New launches |
| Exact model | Shared default model and one model per agent | Project model; workflow `model`; run override; job `model` | New launches |
| Thinking effort | Each agent's Thinking effort | Project agent defaults; job `agent_options.<id>.effort` | Matching exact model |
| Agent permissions | Each agent's What the agent may do | Project agent defaults; job `permission_profile` or `agent_options.<id>.permission_mode` | Matching exact model |
| Job timeout | Job timeout, such as `15m` | Project timeout; agent or command `timeout` | New launches |
| Shared commands | Named program and argument lists | Project command map; job `run: {command: name}` selects one, or declares its own argument list | New command jobs |
| Environment variables | Variable names and string values | Project variable map; workflow `env`; command job `env`; workflow/job `inherit_env` opt-out | New command jobs |
| Automatic retry participation | Allow automatic retries for jobs | Project default; job `auto_retry` | New launches |
| Automatic recovery | Enabled and maximum retries, 1 or 2 | Project policy; explicit workflow `recovery` fields | New launches |
| Working-copy cleanup | After a successful run | Project policy; run launch `cleanup_policy` | New launches |
| Repair rounds | Defaults for new repair rules, 1 through 100 | Project default; saved rule `max_rounds` | New editor rules |
| Repair instructions | Fixer and verifier instructions | Project default; saved rule instructions | New editor rules |
| Login requirement | Server and account | Explicit `relay up --login / --no-login` | Restart required |
| Loopback address | Server and account | Explicit `relay up --host` | Restart required |
| Port | Server and account, 1 through 65535 | Explicit `relay up --port` | Restart required |
| Worker count | Server and account, positive integer | Explicit `relay up --workers` | Restart required |
| Desktop notifications | Notifications | Browser permission and this browser's preference | Immediately |
| Storage locations | Storage shows config, data, logs, and shared instructions | Existing platform/environment path adapters | Read-only in the page |
| Local account | Server and account shows the current account and active login policy | Existing onboarding and sign-in | Read-only in the page |
| Retained data deletion | Storage shows project counts, sizes, and deletion categories | Explicit confirmed project cleanup | On confirmation |

Models resolve in this order: job, explicit run override, workflow, shared
project/global model. If none supplies a model, Relay uses the configured model
of the first agent in the effective agent order. It then requires fresh proof
of that same exact value through the existing routing service. It never tries
another agent's different default model to make a failed launch succeed.

Per-agent effort and permissions inherit only when that agent's configured
model equals the resolved exact model. An explicit job option takes precedence;
an explicit `null` leaves that provider option unset even when a global value
exists. An explicit `permission_profile` also prevents a global permission mode
from replacing it. Changing an agent's model in Settings clears its saved
options. Unsupported saved choices remain errors at launch.

A project model change also clears inherited effort and permissions from the
global model. Explicit project options for the new model still take precedence.

Recovery fields inherit individually; `recovery: {enabled: false}` disables
an inherited policy. Agent and command jobs without a declared timeout inherit
the saved timeout; `timeout: null` explicitly opts out. Human waits and
structural deadlines remain workflow decisions. Native agent ceilings still
apply when the inherited timeout is absent.

Shared commands are named argument lists, such as `test: [python, -m, pytest]`.
A command job selects one explicitly with `run: {command: test}`. Existing
argument lists remain explicit and do not inherit a different command.
Missing names stop launch before a run is created. Programs and arguments
remain separate; Relay does not expand shell syntax or environment variables
inside an argument.

A project's `commands` and `env` overrides each replace the entire global map.
Enabling an override in the browser copies the current effective map so you
can edit or remove entries. An empty map removes all entries for that project.
Turning the override off restores the current global map.

Command variables resolve in this order, with later values winning: global
or replacement project `env`, workflow `env`, then job `env`. They are merged
over the existing worker and resource environment when the process starts.
Workflow `inherit_env: false` skips global/project variables. Job
`inherit_env: false` skips both those variables and workflow variables; its
own `env` still applies over the worker environment. Loop jobs and command
repair roles use their containing workflow's variables. Child workflows use
their own workflow variables, plus project/global defaults, rather than the
parent workflow's variables. These defaults do not configure agent processes.

Launch snapshots capture resolved arguments and variables, including child
jobs and repair roles. Later settings edits affect future runs. Variable
values are stored in local settings and captured run data; Relay does not mask
them in command output. Names must be nonempty and contain neither `=` nor a
NUL character. Values must be strings without NUL characters.

For example, this global file sets Codex first, keeps successful working
copies, and supplies a model and timeout for workflows that omit them:

```json
{
  "agent_preferences": ["codex"],
  "cleanup_policy": "retain",
  "workflow_defaults": {
    "providers": {"codex": {"model": "gpt-6-luna"}},
    "timeout": "15m",
    "recovery": {"enabled": false, "max_retries": 2}
  }
}
```

The model is an example exact value; the installed agent must advertise and
confirm it. Settings reads and model menus never authorize a launch.

Global saves validate the whole file and replace it atomically under a bounded
kernel lock. A stale file hash returns `settings_conflict` and preserves the
newer bytes. Project saves use the same conflict behavior in a database
transaction. Login and server saves change only the next startup; current
access, accounts, and run data remain intact.

Dependency order, conditions, input defaults,
output contracts, instructions, write access, no-op permission, approval
questions/deadlines, loop bounds, subworkflow mappings, repair verdicts, and
entry-point evidence remain explicit workflow choices. They define the task or
its safety boundary and are not injected into every project. Provider login,
credentials, installation, resource bounds, and process ownership stay with
their existing adapters. `--no-browser` remains a startup-only CLI choice.

**Settings › Storage** replaces project-wide cleanup on run pages. It counts
retained reports from database metadata and measures working-copy files without
following inner symlinks. A bounded or unreadable scan shows a lower bound.
Run history shares database pages, and Git references share repository objects,
so the page does not invent per-project disk sizes for those categories.
No deletion category is selected initially. Confirmation describes the category
and current counts; **Everything** also requires typing the project name.
Cleanup still goes through the existing service and rejects active project
runs. Everything also clears Relay's marked process logs across the
installation, as the existing `all` cleanup contract specifies.
