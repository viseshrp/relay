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
the run's advanced view. A replaced directory, symlinked marker, wrong run,
or mismatched token is not followed. Inner links are unlinked without deleting
their targets. Unmarked files are preserved, including during confirmed run
record deletion. Worktrees, retained evidence, provider credentials, and other
Relay runs use separate storage and remain outside temporary cleanup.

On POSIX, each command or agent runs in a new process group; Relay stops its
remaining descendants when the lifecycle ends. On Windows, a launcher joins
an unnamed Job Object before creating the target. Its non-inheritable job
handle uses `JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE`, so surviving descendants stop
when the launcher exits. No cleanup scans personal browser processes or acts
on a PID saved by an earlier Relay instance. See Microsoft's
[Job Objects documentation](https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects).

Files created outside the supplied temporary and profile folders remain
outside Relay's ownership. Cleanup failures are logged and reported as run
events; they do not replace a completed attempt's result.

Unexpected failures in `relay init`, `relay project list`,
`relay project relink`, or `relay data clean` produce the same JSON error
envelope as other administration commands. The local log retains the trace.

Static assets and retained artifact downloads use Python's built-in MIME
tables, independent of operating-system registries and MIME files.

## Retention and deletion

Run history remains until the owner confirms deletion. Project rows are
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
