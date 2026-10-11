# Git worktrees and retained evidence

Relay runs each workflow on a new branch and keeps failed work attributable to
one attempt. It never checks out or rewinds the branch from which the run was
launched. Merging into that branch requires the explicit completion option
described below.

## Clean launch

Before creating a run, Relay executes the equivalent of:

```bash
git status --porcelain=v1 --untracked-files=all
```

Staged changes and code changes stop launch. Exact workflow and local prompt
files validated for this launch may have unstaged edits or be untracked;
their current bytes are captured in the immutable snapshot. The two untracked
files created by `relay init` may also remain when their bytes still match the
blank workflow and empty prompt. Edited unused starter files, staged starter
files, and other `.relay` files stop launch. Root workflow documents such as `REVIEW.md`,
`WALKTHROUGH.md`, and `DRAFT_PLAN.md` may remain unstaged or untracked. Relay
does not add Git exclusions, stage these files, or commit them. Existing owner
documents stay in place. Symlinks and staged report changes still stop launch.

The browser's **Run workflow** panel previews this same rule and explains
blocking and permitted changes. It reads Git status and validates saved
workflow sources without staging, stashing, or committing anything. Launch
checks again before creating a snapshot or working copy, so a preview never
authorizes changes made later.

An unrelated untracked workflow can be committed through **Commit workflow
files** in that panel. Relay first validates its sources and displays every
candidate's contents. Explicit confirmation repeats the validation, checks
the reviewed hashes and Git head, and requires an empty index. It verifies
staged blob contents against those hashes and commits the checked index,
so a later working-file edit cannot enter the commit. Invalid unrelated
workflow candidates are skipped with a notice; invalid sources referenced by
the launch still fail validation. The resulting commit contains only those
workflow and referenced prompt paths. Root reports,
unused prompt files, and unrelated code are excluded. This action does not
change any launch or writer cleanliness exemption.

These report exemptions apply to writing-node cleanliness too, so a report
can be preserved and passed to the next stage without a documentation commit.
Autonomous workflows can also leave `E2E_VERIFICATION.md`,
`PLAN_CHECKPOINT.json`, `REVIEW_CHECKPOINT.json`, `AUDIT_CHECKPOINT.json`, and
`E2E_CHECKPOINT.json` unstaged in the repository root. These exact names are
reserved for run reports and machine-readable verdicts. Nested files and other
JSON files remain subject to the normal Git checks.
Read-only nodes still fail for any worktree modification. Unrelated code
changes remain errors. A clean dashboard or unchanged `HEAD` does not replace
the Git checks.

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

Before executing each attempt, Relay checks that its primary checkout belongs
to the registered Git repository. A mismatched checkout fails the attempt
before the agent or command runs, and normal fail-fast scheduling stops its
downstream work. Agent context identifies the project and assigned checkout.

The run branch remains after success, failure, cancellation, and worktree
cleanup. By default, the owner decides whether and how to inspect, merge, or
delete it. The opt-in integration policy can merge successful run commits.

## Actions job boundaries

Current workflows execute one job at a time across the installation. Every
step in a physical job uses its primary run worktree, including agents,
scripts, composites, and owner waits. Steps can leave code edits for later
tests and commits. At job success, code changes require a clean descendant
commit; a clean no-op is valid. Report exemptions remain unchanged.

Accepted commits advance the protected run head cumulatively. Failed jobs
retain commits, diffs, untracked bytes, and reports. Before another job
continues, Relay verifies that evidence, records continuation intent, moves
the rejected checkout into a retained detached worktree, and recreates the
primary at the protected head. A journal resumes interrupted continuation
without discarding rejected bytes or resetting the owner's checkout.

Matrix and reusable jobs use the same serial admission. Tolerating a failure
changes dependency conclusions without accepting rejected code. Optional
named artifact expiry and cache eviction never delete required evidence.

## Historical reader and writer admission

The following admission contract applies to captured legacy `nodes` runs.
Current source uses [jobs and ordered steps](workflows.md).

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

1. The primary worktree has no staged or code changes; unstaged root workflow
   documents are retained as described above.
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

Interrupted loops and subworkflows check the primary checkout against the
latest protected head without resetting it. Unstaged root report handoffs keep
the same exact exemptions as completed writers. Code changes, staged reports,
nested report files, and an unrecorded head still stop recovery. Restart keeps
an owner's dispatch pause, so recovery does not start held child steps.

Manual rerun, automatic recovery, and interrupted resume use this order:

1. Stop the attempt process.
2. Preserve its ref, commits, diff, untracked files, and declared artifacts.
3. Verify the complete manifest, each recorded file's byte count and SHA-256,
   and the retained ref's commit. Missing, changed, or escaping evidence blocks
   recovery while the current worktree remains intact.
4. Prove the reset target descends from the latest successful writer's
   protected head.
5. Reset the primary worktree to the attempt's recorded starting head.
6. Remove remaining untracked files from that isolated worktree.

The protection check prevents a failed later attempt from erasing a successful
upstream writer. Evidence remains available when the reset itself fails.

Output extraction can reject a report without discarding its bytes. Existing
files behind `label`, `json_path`, and `yaml_path` selectors are retained even
when required labels or values are invalid. Missing files remain validation
errors; escaping paths block recovery. Commit validation failures also retain
the attempt's partial work before a retry can reset it.

Recovery restores verified root report handoffs into the primary writer
worktree from successful steps and the selected failed attempt. Detached
readers use retained evidence without adding files to their checkout.
Only names already exempted in
`WORKFLOW_DOCUMENT_NAMES` are restored. Other source files remain evidence
rather than untracked inputs. Relay checks each retained report's hash before
reset and before restoration. Different existing bytes and symlinks block
restoration instead of being overwritten. Older failed attempts may gain a
`recovery-reports` supplement; their original retained ref, manifest, and file
bytes remain unchanged.

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

The execution store refuses completion cleanup if any artifact record has not
been preserved. Confirmed data cleanup removes known worktrees deepest first,
so reader paths precede the primary.

The [cleanup API](http-api.md#cleanup) can select a single run with `run_id`.
Use `scope: "worktrees"` to discard its checkout while retaining history,
artifact bytes, the protected run branch, and attempt refs. Other runs remain
unchanged. This selection requires preserved artifact records and holds the
same workspace lock as recovery, so a retry cannot reopen the checkout during
removal. The project must have no active runs. Deleting a selected run with
`scope: "all"` leaves shared process logs in place.

## Opt-in run integration

Select **Merge into the active branch, then delete working copies** in global
defaults, project defaults, or Run workflow. The API and settings value is
`cleanup_policy: "merge_on_success"`. Existing defaults stay unchanged.

All writing jobs already commit onto one run branch. Read-only jobs have no
changes to merge; their detached working copies are removed after each attempt.
After every job succeeds or is skipped, Relay performs these steps:

1. Record the run as `completing`, keeping the live event stream open.
2. Verify retained evidence and the run's recorded commit. Acquire the run's
   workspace lock and a repository-wide integration lock.
3. Require the original checkout to be on the branch captured at launch and
   completely clean. Staged changes, unstaged changes, and untracked files all
   block integration, including workflow sources and root reports. Ignored
   files follow Git's normal status rules. An unfinished merge, rebase,
   cherry-pick, or revert also blocks it.
4. Fast-forward that branch to the validated run commit, with automatic
   stashing and Git hooks disabled. A diverged branch fails without creating
   conflicts or changing the owner's checkout. Relay never switches branches.
5. Record `merged_commit`, remove the primary run worktree, and record success.
   Run history, artifacts, the run branch, and attempt refs remain available.

Merge-enabled launches also require the strictly clean checkout and an attached
branch. Commit workflow and report edits before launching with this option.
The launch file preview uses the same strict policy.

A dirty, switched, or diverged branch fails the run and retains its worktree.
Completed jobs remain successful and retain their outputs. If deletion fails
after merging, the run fails and shows the recorded merged commit and retained
working copy. Relay does not undo an already completed merge.
Startup reconciliation resumes runs left `completing`, including a crash after
Git updated the branch but before the database recorded it, or after removing
the worktree. It recognizes the integrated commit instead of merging twice.
Pause and cancellation cannot interrupt this final integration step.

## Privacy and storage

Diffs, untracked files, declared artifacts, commit metadata, and manifests may
contain secrets or proprietary code. They stay in the owner's central Relay
data directory and are retained until confirmed deletion. Relay does not mask
their contents or send telemetry.

See [Projects and storage](projects-and-storage.md) for platform paths and
retention boundaries. See [Workflows](workflows.md) for `writes`,
`allow_no_commit`, and artifact selectors.
