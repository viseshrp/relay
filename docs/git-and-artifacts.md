# Git worktrees and retained evidence

Relay runs each workflow on a new branch and keeps failed work attributable to
one attempt. It never checks out, rewinds, or merges the branch from which the
run was launched.

## Clean launch

Before creating a run, Relay executes the equivalent of:

```bash
git status --porcelain=v1 --untracked-files=all
```

Any staged, tracked, or untracked record stops launch. Commit, move, or remove
the change and start again. Relay repeats cleanliness checks around every node
attempt. A clean dashboard or an unchanged `HEAD` does not replace this check.

## Run branch and primary worktree

For run ID `abc-123`, Relay creates:

```text
branch:   relay/run/abc-123
worktree: <data>/worktrees/abc-123
```

The branch starts at the full source commit selected during launch. Relay
passes every Git command as an argument vector with `shell=False`; no shell
quoting or platform-specific command string is involved. A pre-existing branch
or worktree path is treated as a collision rather than reused.

The run branch remains after success, failure, cancellation, and worktree
cleanup. Relay has no automatic merge. The owner decides whether and how to
inspect, merge, or delete it.

## Reader and writer admission

A writing attempt holds the run's exclusive database lock while it uses the
primary worktree. No reader or second writer can start until that lock is
released after commit validation and evidence preservation.

Read-only attempts may run together. Each receives a detached worktree at the
run's recorded committed `HEAD`:

```text
<data>/worktrees/abc-123/r-12
<data>/worktrees/abc-123/r-13
```

Git reports these nested reader directories as transient untracked paths from
the primary checkout. Admission therefore prevents any writer or primary
cleanliness boundary while readers exist. Each reader is checked in its own
worktree, removed before its lock is released, and leaves the primary clean
again. This ordering prevents a reader directory from being mistaken for
agent work.

A reader fails if it changes a file or moves detached `HEAD`. Relay preserves
that reader's diff before removing the worktree. Mark a node `writes: true` if
it is intended to change the repository.

## Writing-node commits

Agents and writing commands commit their own work. After a writing node ends,
Relay requires all of these conditions:

1. The primary worktree has no staged, tracked, or untracked changes.
2. Ending `HEAD` descends from the attempt's recorded starting `HEAD`.
3. At least one commit exists in that range.

The third condition may be waived only by declaring `allow_no_commit: true`
on a writing node whose valid result can be a no-op. Relay accepts one or more
commits and records the ending `HEAD` as the next protected head.

An ancestry check is the equivalent of:

```bash
git merge-base --is-ancestor STARTING_HEAD ENDING_HEAD
```

Status `0` proves ancestry; status `1` rejects it. Relay does not infer success
from a commit message or file count.

## Attempt evidence

Before any reset or worktree removal, Relay creates an immutable directory at:

```text
<data>/artifacts/<run-id>/<attempt-id>/
```

It contains:

| Path | Evidence |
| --- | --- |
| `manifest.json` | Version, run, attempt, heads, retained ref, paths, hashes, sizes, media types. |
| `commits.txt` | Partial commit IDs from the attempt's starting head to ending head. |
| `diff.patch` | Binary-capable staged and tracked worktree diff against `HEAD`. |
| `untracked/` | Exact bytes and relative paths of regular untracked files. |
| `untracked-symlinks/` | Symlink target text, stored as inert text rather than a live link. |
| `declared/` | Copies of workflow-declared artifact files. |

For run `abc-123`, attempt `12`, the ending commit is also protected by:

```text
refs/relay/attempts/abc-123/12
```

The run ID and attempt ID become separate ref path segments exactly as shown.
An existing evidence directory or ref is never overwritten. Regular files are
copied in 1 MiB chunks, and SHA-256 is calculated over the retained bytes.
Symlink targets that point outside the worktree are never followed. A declared
artifact is accepted only when its resolved target is a regular file inside
the attempt worktree.

The files are written to a private staging directory, flushed, and renamed to
the final attempt directory. The retained ref is created first, so partial
commits survive even if a later file copy fails. A preservation failure blocks
reset and cleanup.

## Rerun and resume reset

Manual rerun and interrupted resume use this order:

1. Stop the attempt process.
2. Preserve its ref, commits, diff, untracked files, and declared artifacts.
3. Prove the reset target descends from the latest successful writer's
   protected head.
4. Reset the primary worktree to the attempt's recorded starting head.
5. Remove remaining untracked files from that isolated worktree.

The protection check prevents a failed later attempt from erasing a successful
upstream writer. Evidence remains available when the reset itself fails.

## Completion cleanup

`clean_on_success` removes primary and reader worktrees only after preservation
succeeds. `retain` keeps them for inspection. Failure retains the workspace by
default. Every run branch and attempt ref remains until an explicit confirmed
data-clean operation.

Relay calls `git worktree remove --force` for an exact known path. On Windows,
file-lock failures receive three bounded delays: 50 ms, 200 ms, then 800 ms.
Linux and macOS make one attempt. An unrecoverable removal reports the path and
keeps its evidence and refs; Relay does not fall back to deleting an uncertain
directory tree.

Worktrees are removed deepest first, so reader paths precede the primary. A
caller must explicitly prove evidence preservation before the cleanup helper
will remove anything.

## Privacy and storage

Diffs, untracked files, declared artifacts, commit metadata, and manifests may
contain secrets or proprietary code. They stay in the owner's central Relay
data directory and are retained until confirmed deletion. Relay does not mask
their contents or send telemetry.

See [Projects and storage](projects-and-storage.md) for platform paths and
retention boundaries. See [Workflows](workflows.md) for `writes`,
`allow_no_commit`, and artifact selectors.
