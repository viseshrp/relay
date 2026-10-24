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

These report exemptions apply at job acceptance too, so a report
can be preserved and passed to the next stage without a documentation commit.
Autonomous workflows can also leave `E2E_VERIFICATION.md`,
`PLAN_CHECKPOINT.json`, `REVIEW_CHECKPOINT.json`, `AUDIT_CHECKPOINT.json`, and
`E2E_CHECKPOINT.json` unstaged in the repository root. These exact names are
reserved for run reports and machine-readable verdicts. Nested files and other
JSON files remain subject to the normal Git checks.
Unrelated files must be included in the accepted job commit or removed by the
workflow. A clean dashboard or unchanged `HEAD` does not replace Git checks.

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
continues, Relay preserves missing evidence from the rejected checkout and
verifies that each failed job and step attempt it holds has complete evidence.
A preservation failure blocks the next job. Only then does Relay record
continuation intent, move the rejected checkout into a retained detached
worktree, and recreate the primary at the protected head. Retained checkouts
sit beside the primary as `<run-id>-failed-1`, `<run-id>-failed-2`, and so on;
short names keep Windows paths within their 260-character limit. A journal
resumes interrupted continuation without discarding rejected bytes or resetting
the owner's checkout.

Matrix and reusable jobs use the same serial admission. Tolerating a failure
changes dependency conclusions without accepting rejected code. Optional
named artifact expiry and cache eviction never delete required evidence.

## Job admission and commits

One durable installation-wide job lease admits a physical job and its nested
steps. Every step shares the run's primary worktree. Steps retain evidence;
Relay commits changed code once when the job succeeds. A clean no-op is valid.

The accepted head must descend from the job's starting head. Staged report
files, staged captured sources, unresolved conflicts, and unrelated history
block acceptance. Commit messages do not prove success.

## Attempt evidence

Job and step attempts retain evidence, except `relay/human-wait@v1` steps.
Human waits persist owner answers; their enclosing job retains the shared
worktree. If another attempt ends before preservation, Relay preserves its
missing evidence from the current workspace before a retry or confirmed
worktree cleanup, then verifies it. Existing evidence is never replaced.

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
| `INDEX.md` | Failed attempts only: error code, every retained path with its size and purpose, and the failure message. |

For run `abc-123`, attempt `12`, the ending commit is also protected by:

```text
refs/relay/attempts/abc-123/12
```

The run ID and attempt ID become separate ref path segments exactly as shown.
A step with `allowed-paths` also keeps its starting snapshot reachable as
`refs/relay/attempts/<run-id>/scope-<step-id>`, a parentless commit whose tree
is the recorded worktree content. Git garbage collection therefore cannot
remove the snapshot that later retries compare against, and confirmed run
cleanup removes it with the run's attempt refs. Storage usage and cleanup
results count only attempt refs, not these snapshots.
An existing evidence directory or ref is never overwritten. Regular files are
copied in 1 MiB chunks, and SHA-256 is calculated over the retained bytes.
Symlink targets that point outside the worktree are never followed. A declared
artifact is accepted only when its resolved target is a regular file inside
the attempt worktree.

`INDEX.md` is written for failed attempts and recorded in `manifest.json` with
its hash, so changing it fails verification like any other retained file. Its
failure message keeps at most 64 KiB, masks registered run secrets, and cannot
close its own code fence. For example, a rejected report appears as
`declared/report` with the label `` (`report`) `` next to the full
validation error. Automatic recovery names this file in its repair
instruction.

The files are written to a private staging directory, flushed, and renamed to
the final attempt directory. The retained ref is created first, so partial
commits survive even if a later file copy fails. A preservation failure blocks
reset and cleanup.

## Rerun and resume

An owner retry verifies the failed attempt's manifest, retained ref, file sizes,
and SHA-256 hashes before reopening it, preserving missing evidence first for
attempts that require it. Human-wait steps require no evidence. It also checks
the primary worktree against the protected head. Root report handoffs retain
the same exact exemptions used at job acceptance. Code changes, staged reports,
nested report files, and an unrecorded head require an owner decision.

Inline bounded agent recovery stays inside the current job. It retains rejected
reports and partial work, checks preserved evidence, and continues the failed
step without repeating completed steps. Failed runs keep their private job
state for an owner retry. Successful completion or explicit confirmed resource
cleanup removes that state.

Orderly restart verifies retained workspaces before resuming current job and
step scopes. It preserves an owner's dispatch pause. A failed job's workspace
is preserved before an unrelated job continues at the last accepted head, as
described under [Actions job boundaries](#actions-job-boundaries).

Existing files required by report selectors are retained even when validation
fails. Missing or escaping paths remain errors; a successful agent turn alone
does not establish that its report passed.

## Completion cleanup

`clean_on_success` removes run worktrees only after preservation
succeeds. `retain` keeps them for inspection. Failure retains the workspace by
default. Every run branch and attempt ref remains until an explicit confirmed
data-clean operation.

Relay calls `git worktree remove --force` for an exact known path. On Windows,
file-lock failures receive three bounded delays: 50 ms, 200 ms, then 800 ms.
Linux and macOS make one attempt. An unrecoverable removal reports the path and
keeps its evidence and refs; Relay does not fall back to deleting an uncertain
directory tree.

Before removing a checkout, automatic and confirmed cleanup verify its attempt
manifests, retained refs, and artifact hashes. Missing artifact rows cannot prove
preservation succeeded. Incomplete evidence blocks cleanup before any checkout
in a bulk request is removed. Confirmed data cleanup removes retained failed-job
workspaces before the current primary worktree.

The [cleanup API](http-api.md#cleanup) can select a single run with `run_id`.
Use `scope: "worktrees"` to discard its checkout while retaining history,
artifact bytes, the protected run branch, and attempt refs. Other runs remain
unchanged. This selection verifies retained evidence and holds the same
workspace lock as recovery, so a retry cannot reopen the checkout during
removal. The project must have no active runs. Deleting a selected run with
`scope: "all"` leaves shared process logs in place.

## Opt-in run integration

Select **Merge into the active branch, then delete working copies** in global
defaults, project defaults, or Run workflow. The API and settings value is
`cleanup_policy: "merge_on_success"`. Existing defaults stay unchanged.

Jobs commit their changes onto one run branch.
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
retention boundaries. See [Workflows](workflows.md) for job boundaries and
report selectors.
