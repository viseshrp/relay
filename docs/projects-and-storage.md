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
`relay.db`, `huey.db`, `snapshots/`, `artifacts/`, `worktrees/`, and
`registry-cache/`. The log root contains `relay.log` and supervisor logs.

## Database and disk roles

`relay.db` is the durable source for projects, drafts, editor leases, runs,
snapshots, scoped nodes, attempts, dispatch claims, events, artifacts,
interactions, control requests, agent observations, and run locks. SQLite uses
foreign keys, WAL mode, and a five-second busy timeout. Contention beyond that
limit becomes a Relay persistence error.

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

## Retention and deletion

Run history remains until the owner confirms deletion. Project rows are
protected while runs reference them. Deleting a run may cascade only through
that run's owned snapshot, nodes, attempts, events, interactions, controls,
and artifact metadata.

Evidence preservation precedes worktree removal. Relay does not delete the
only copy of a diff, artifact, or snapshot without confirmation. Retained run
branches require explicit cleanup even when a successful worktree is removed.

Agent and command processes inherit the worker environment. Relay has no secret
vault or output masking, so the database, artifact directory, and logs may
contain sensitive prompts, responses, command output, and tool results.

See the [README](../README.md) for installation and the local-only product
boundary.
