# Windows validation after removing workflow v1

Date: 2026-10-15. Relay now accepts the current `jobs` and `steps` workflow
language only. The `version: 1` / `nodes` parser, executors, replay fallback,
implicit repair rules, reader worktrees, and browser controls are removed.
Current built-ins such as `relay/agent@v1` still version their action API;
they do not enable the removed workflow language.

Migration `0017_remove_legacy_workflows` removes obsolete execution fields
and locks. It normalizes existing Actions plans without recompiling source.
Unsupported captures retain source, prompts, hashes, and opaque metadata as
evidence. They cannot launch, resume, retry, or recover through the worker.
The migration tests use disposable databases. No owner database was migrated
or reset during this validation.

## Windows checks

The host uses Windows 11 x64 build 26300, Python 3.14.7, Node 24.12.0,
PowerShell 7.6.5, Git 2.54.0.windows.1, uv 0.12.5, and Playwright 1.63.0.
Node 20.20.2 was also supplied to the complete Python run.

The [structured record](2026-10-15-windows-actions-only.json) identifies the
tested commits, source trees, report hashes, and accepted browser outcomes.
It excludes credentials, raw provider output, and private diagnostic logs.
The [pull request](https://github.com/viseshrp/relay/pull/23) records subsequent
native reruns and hosted results; this file preserves the checkpoints below.

| Check | Result |
| --- | --- |
| Complete native Python checkpoint, `32b3166` | 2,802 collected: 2,770 passed, 32 declared skips; completeness verifier passed |
| Initial complete Python checkpoint, `6e23ab4` | 2,798 collected: 2,766 passed, 32 declared skips |
| Additional approval, artifact, and fixture regressions | Six passed; final fixture retest: two passed |
| Functional Chromium inventory | 297 passing cases across isolated shards and focused retests |
| Focus regression, onboarding, project setup, and workflow navigation | 20 passed after the delayed-response regression failed before the fix |
| No-login / monitor unit tests | 4 / 16 passed |
| Windows visual and layout suite | 29 passed without updating snapshots |
| Build-script and expression tests | 1,036 passed; five declared oracle cases skipped |
| Frontend build, ESLint, Prettier, TypeScript | Passed |
| Repository quality and documentation checks | Passed |
| CodeQL cleanup: workflow loading, validation, recovery, and heartbeats | 165 passed; two symlink-privilege skips |
| Wheel and source-distribution build and content checks | Passed at `6e23ab4` |
| Installed wheel with Node and npm absent from PATH | HTML, auth API, and compiled JavaScript served; clean shutdown |

The native Python skips are 22 cases requiring unavailable symlink privileges
and ten declared platform cases. The real Windows directory-junction test
passes. Node 20 and Node 24 tests execute in the full run; neither runtime is
missing. The suite verifier checks inventory completeness across the serial
and parallel lanes.

One intervening run passed its cases but failed the checkout-identity verifier
because this task committed changes during collection. That report is not
accepted as a complete pass. The independent rerun used a fixed disposable
checkout at `32b3166`; all 2,802 cases and both lane identities verified.

The functional browser record selects one passing outcome for every current
case. It has no omissions, skips, or automatic retries. Earlier failures and
manual retests remain separate reports. Each server uses independent Git,
database, configuration, and storage roots. The final visual suite compares
21 reviewed Windows screenshots and runs eight structural/layout checks.
Linux screenshots come from the dedicated hosted generation workflow and
are reviewed separately.

## Defects found and retested

| Defect | Correction and evidence |
| --- | --- |
| Ordinary output incurred one transaction per line | Batch each process read, retain bounded events and ordering; the original 20,000-line regression passes. |
| Failed-run cleanup removed job state needed for retry | Retain failed allocations until retry, success, or explicit cleanup; recovery tests pass. |
| Worker-loss detection excluded live agent waits | Distinguish yielded scopes from live agent sessions; process-ownership regressions pass. |
| A due quota reset did not wake its enclosing job | Wake once using a durable event identity; retain completed work and owner pause. |
| Unknown or expired quota observations could authorize retry | Retain a blocked retry record; deterministic usage tests pass. |
| Canceling yielded scopes could strand cleanup | Redispatch their existing cleanup intent while preserving live-session controls. |
| An absent optional input appeared supplied as an empty string | Distinguish explicitly supplied values and defaults; entrypoint tests pass. |
| Omitted agent retry settings overrode owner defaults | Compile only explicit step overrides; owner-setting and recovery tests pass. |
| Job activity filters missed descendant step events | Include ordered descendant activity; event and browser tests pass. |
| Native soft-denial checks depended on the removed writer flag | Require the complete verified worktree stderr notice; deterministic Antigravity tests pass. |
| Fatal job failures lost their public failure summary | Keep the already masked attempt message when settling the run. |
| Retry validation could bypass the database error envelope | Keep validation inside the repository's error boundary; outage tests pass. |
| Human approval blocked successful merge validation | Approval records only an answer; validate the enclosing job archive and executable steps. Clean merge and dirty-owner-target regressions pass. |
| Generated artifact names were invalid storage filenames | Store logical `subject:...` names under hashed filenames, retaining original metadata and verified bytes. ASCII, Unicode, and late-artifact browser regressions pass. |
| A delayed default workflow stole focus after the checklist closed | Preserve focus when initial workflow loading fills the URL. A controlled browser regression fails before the fix and passes afterward; explicit navigation still focuses the main view. |

Old browser fixtures assumed simultaneous job admission, implicit report
retention, or YAML reparsing. They now use current frozen plans, serial
admission, explicit artifact declarations, and bounded execution readiness.
Approval screenshots wait for the actual job to load. Explicit repair loops
still execute as current Actions workflows.

Five new CodeQL comments identified a redundant callback wrapper, a protocol
placeholder, and three import-cycle edges. Shared workflow records now live
in `relay/workflows/records.py`; loader, compiler, and validator no longer
import each other for these types. The recovery callback is passed directly,
and the admission protocol documents its state-ordering contract.

## Fresh live Claude check

At `6e23ab4`, Claude Code 2.1.300 through ACP adapter 0.91.0 completed a
production Actions workflow in a disposable Windows project. Fresh model
selection confirmed the literal advertised value `default`; it does not
identify Claude's concrete backend model. Effort and permission overrides
remained unset. Two exact diagnostic/file requests received one-use answers.

The command emitted Unicode stdout, stderr, intentional structured exit code
3, and a synthetic secret split across writes. Public tool events retained
the diagnostics and masked the secret. The agent wrote `PROVIDER-RETEST.md`;
Relay verified its label, retained its exact bytes, committed once at the
job boundary, and advanced the protected head. The 225-byte report has SHA-256
`aa05fa2ba3b07a2fc074d0a5f8cb2128f191257860a4aa5607d2cc31f7de47a1`.

All eight downloads matched their recorded hashes before and after worktree
cleanup. The launch checkout stayed clean and on its captured head. Provider
process identities cleared, the supervisor and its children stopped
cooperatively, and its ownership record disappeared.

An earlier diagnostic run timed out while the test helper waited to inspect
a command with an extra exit-code echo. Its record remains separate. The
successful retest required the exact diagnostic command; it did not change
the selected model or enable blanket approval. Both worktrees were removed
through Relay's confirmed cleanup API.

The two later production fixes concern approval merge validation and artifact
subject storage; focused Windows regressions cover them. Later complete runs
are recorded on the pull request. This pass does not recertify other live
providers or operating systems. Earlier provider evidence remains tied to
its original commits.

No SuspendIt files changed in this removal pass. The owner's three untracked
review documents remain unchanged historical snapshots. Merge stays on hold.
