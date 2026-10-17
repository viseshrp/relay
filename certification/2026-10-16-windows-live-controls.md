# Windows live controls and certification fixes

Date: 2026-10-16 UTC. This pass tests Relay in disposable projects and isolated
storage on Windows 11 x64. The
[structured record](2026-10-16-windows-live-controls.json) contains exact
checkpoints, versions, run IDs, source and artifact hashes, complete test
inventories, and cleanup results. Later gate results are recorded on
[PR 23](https://github.com/viseshrp/relay/pull/23). Merge remains on hold.

## Live Windows checks

| Check | Result |
| --- | --- |
| Fresh Codex ACP 2.2.2 / Codex 0.160.1, `gpt-6.1-sol` | Passed relative command execution, Unicode stdout and stderr, intentional exit code 3, split-value masking, retained report, one job commit, browser display, and cleanup. |
| Antigravity 1.3.6, `gemini-3.8-flash-low` | Passed the native headless path with `accept-edits`, exact UTF-8 report bytes, one job commit, browser display, and cleanup. |
| Owner cancellation | Codex stopped all 29 recorded process identities in 4.73 seconds, including the command and its child. Native Antigravity stopped its three recorded identities in 2.20 seconds. Both retained canceled outcomes and evidence. |
| Provider timeouts | Real Codex and native Antigravity commands ran with children beyond a one-minute deadline. Relay recorded `node_timeout` / `timeout`, stopped the recorded trees, retained evidence, and required no owner cancellation. |
| Structured elicitation | The real Codex question rendered its offered choices. Chrome submitted `staging (Recommended)`; the same attempt and session acknowledged that exact value and completed with a clean no-op job. |
| Model drift | An ACP forwarding proxy injected one model-selection notification during a real authenticated Codex attempt. Relay rejected it with `model_selection_rejected_error`, retained the original exact model, and made no fallback or automatic retry. This is controlled fault injection, not naturally occurring provider drift. |
| Native permission denial | An isolated Antigravity home requested approval for writes under `respect_settings`. The provider returned exit zero and `SUCCESS`, but Relay recorded `antigravity_soft_denied` / `soft_denied` and retained the denied-write evidence. |

The elicitation proxy selects Codex's advertised `collaboration_mode=plan` to
enable its structured question tool. It forwards the real ACP conversation;
the selected model, effort, and permission overrides remain unchanged.
Native permission tests use disposable settings files rather than changing
the owner's Antigravity configuration.

Successful reports, declared artifacts, manifests, refs, and archived bytes
matched their recorded hashes. Worktree cleanup removed only the selected
test worktree. Every retained artifact was downloaded and verified again
after cleanup. Recorded provider process IDs cleared. Lab shutdown used the
durable orderly-shutdown request and verified the supervisor's creation
identity and children had exited; it is not a Ctrl+C exit-code certification.

## Defects found and fixed

1. Windows private-directory ACLs allowed sandbox-created files to exclude
   Relay's owner. The original owner now inherits full control without losing
   existing ACL entries or DACL protection. Native ACL tests cover direct
   directories and attempt-resource allocation.
2. Node and PowerShell needed parent-directory attributes to resolve the
   assigned workspace. A directory-only `ReadAttributes` grant fixes relative
   commands without granting directory listing or file reads. A real Codex
   sandbox probe verified those boundaries.
3. Cleanup could delete a failed worktree when preservation failed before
   creating Artifact rows. It now requires complete manifests, protected
   refs, and matching bytes before deleting any selected worktree. All four
   selected-run and bulk cleanup regressions failed before the fix and passed
   afterward. The first disposable report's original bytes were lost before
   this guard existed; this record does not claim to recover them.
4. ACP `oneOf` choices appeared as free-text fields, and an offered empty
   string could not be submitted. Choice controls now preserve exact values,
   labels, descriptions, ordering, and explicit empty selections. Tests check
   the durable response and the real fake-ACP wire answer.
5. Antigravity's generic advice contains `write_file(<target>)`. Relay mistook
   the placeholder, and command examples, for workspace write targets. The
   adapter now correlates a complete native notice with the actual failed
   write and its permission error. Seven regression cases cover concrete and
   outside targets, help text, command denials, unrelated write errors,
   stdout-only prose, and reversed pipe order. Job and embedded step notices
   also use the semantic failure reason instead of saying exit zero failed.

The ACL test observer now uses canonical SIDs and native permission values,
works under PowerShell 5 and 7, and avoids module-discovery delays. CI collects
native Windows coverage on Python 3.14 alongside Linux coverage. The new
CodeQL import-style comment is addressed by consistent `ctypes` imports.

## Automated checkpoints

At `9c6dc95`, `uv run tox -e py314` collected 2,815
Windows Python tests: 2,783 passed and 32 declared skips. The native
inventory verifier confirmed every serial and parallel outcome exactly once.
The skips comprise 22 symlink-privilege cases and 10 declared platform cases.
The final UI checkpoint `3cffed5` has the identical Python
production tree; its later changes concern the browser and its test fixture.

At `3cffed5`, the wheel and source distribution passed metadata and content
checks. A fresh wheel installation served the compiled application with Node
and npm absent from PATH, then stopped with no supervisor lease remaining.

The native adapter checks passed all 34 cases. Before the denial fix, six of
the seven new cases failed and one passed. The elicitation checks passed all
three choice cases, with 29 related browser checks also passing. The native
denial browser regression and five affected failure/retry scenarios passed.

The initial complete Windows browser attempt at `8576a9a` passed 299 of 300
functional cases and stopped at workflow authoring: the Steps tab remained
unselected after a pointer click. Five unchanged focused repeats passed.
The test now waits for the drawer entrance to finish and asserts tab
selection; five further repeats passed. The failed report and trace remain
fingerprinted. The complete final browser rerun is reported separately on
the PR; this record does not convert that initial failure into a pass.

At the hosted `8576a9a` checkpoint, all 15 Python environments passed:
42,010 passed and 110 declared skips across 42,120 collected outcomes. The
349-case browser inventory also passed. Downloaded inventories and native
reports independently verified every outcome, checkout, partition, and
absence of retries. CodeQL and both Codecov checks passed. GitHub tested
merge checkout `a7c54d2`, whose second parent is `8576a9a`; the record keeps
that distinction. Later checks must be read from the current PR head.

## Linux provider check and remaining sign-ins

Copilot CLI 1.0.98 completed an authenticated workflow with the exact
advertised selector `auto`, two one-use permission answers, Unicode output,
intentional exit code 3, masked output, a retained report, one job commit,
verified process cleanup, and successful worktree cleanup. All eight
downloads still matched their hashes after cleanup. `auto` does not identify
Copilot's chosen backend model.

These processes ran as an unprivileged Linux user in an official Debian
bookworm Python container under Windows WSL2. This certifies that Linux
environment, not a separate physical Linux desktop. Provider credentials
remain inside the disposable Linux home and are excluded from this evidence.

Linux Claude, Cursor, and Antigravity are installed but still need account
sign-in. The previous Cursor login link expired. Their live provider runs
remain blocked on authentication. Linux Codex is deferred at the owner's
explicit request. No successful Linux certification is claimed for those
four providers.

The owner's three original untracked review documents remain unchanged
historical snapshots. No SuspendIt files or owner Relay storage changed in
this pass.
