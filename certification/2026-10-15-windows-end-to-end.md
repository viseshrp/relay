# Windows automated verification, 2026-10-15

The follow-up closes the 13 Windows browser failures recorded at `d977ca8`.
Broader execution also exposed short workflow waits, competing checklist focus
restoration, and a Git revision-query failure in deep Windows paths. These are
fixed in the tested code checkpoint `83072e0`.

## Environment and scope

| Component | Version |
| --- | --- |
| Host | Windows 11 x64, build 26300 |
| Python | CPython 3.14.7 |
| Node | 24.12.0; 20.11.1 for local JavaScript action tests |
| PowerShell | 7.6.5 |
| Git | 2.54.0.windows.1 |
| Playwright | 1.63.0, Chromium |
| uv | 0.12.5 |

Tests used disposable Git repositories, isolated databases and storage, and
deterministic provider subprocesses. PowerShell's directory and Git for Windows
were added to each test process's PATH. No installed provider accounts were used.

The full Python run tested backend checkpoint `5e1c646`; subsequent code commits
change only frontend code and browser tests. The final browser, build, and
distribution checks tested `83072e0`. Its Git tree is
`b8ca08f376aadd99e098043ef80b660b1a4964b9`.

## Fixes and regression evidence

| Area | Change and verification |
| --- | --- |
| Fixture cleanup | Canonical paths select projects under the owning scratch server root with the host's separator. Reseeding removes real runs launched from fixture projects and preserves unrelated projects. The new Python regression failed with the original unique-run-number collision and passed after the fix. The monitor-to-theme/title browser sequence passes. |
| Script and log fixtures | Repair scripts use the built-in Python shell; the named script quotes its output. Raw downloads are compared with the host's exact line endings, including Windows CRLF. The download content is not normalized. |
| Execution readiness | Browser checks wait for the expected workflow state with bounded process-execution budgets and reject unexpected terminal states. Large graphs and the full starter have explicit scenario budgets. UI assertions retain their five-second default. Exact attempts, providers, outputs, and retained reports remain asserted. |
| Editor and settings readiness | Job settings wait for the drawer transition and selected tab panel. Contrast checks wait for visible inputs before measuring every outline. Existing containment, contrast, and accessibility assertions remain intact. |
| Git revision ranges | `rev-list` ends revision operands with `--`. A real repository with a 190-character path and an 82-character SHA range reproduced the original filename-probe failure. The new regression verifies both a committed change and an empty range; the VCS file passes 65 tests with one privilege skip. |
| Checklist focus | App owns restoration to the help or account menu. The checklist disables MUI's competing restoration. Button, Escape, and backdrop dismissal pass browser focus checks; two new cases cover Escape and backdrop. |

## Native Windows results

| Check | Result |
| --- | --- |
| Full Python suite | 2,975 collected: 2,943 passed, 32 skipped; zero failures |
| Full functional browser suite | 288 passed across four isolated shards: 73, 71, 78, 66 |
| No-login browser suite | 4 passed |
| Monitor unit suite | 16 passed |
| Structural visual checks | 8 passed, including containment and layout-shift bounds |
| Frontend build-script and expression tests | 1,036 passed; five declared oracle cases skipped |
| Quality | Repository hooks, Ruff, types, frontend lint/format, lock consistency, and diff checks passed |
| Distribution | Wheel built from the source distribution; both pass metadata and content validation |

The native Python inventory/JUnit verifier accounts for every collected case
exactly once across serial and parallel lanes. The 32 skips comprise 22 symlink
creation privilege skips, five POSIX process-group cases, four Linux-only browser
artifact command cases, and one Windows Job Object lifecycle case. The real
directory-junction regression passed. Both declared Node runtimes executed.

Native Playwright inventories and the repository result verifier account for
all 316 Windows browser/unit/layout cases exactly once, with zero omissions,
duplicates, skips, retries, or snapshot updates. The final acceptance run passed
after the full Python run completed. Earlier failed diagnostic runs were
retained separately and are not counted as passing evidence.

The initial full Python diagnostic used an unnecessarily deep temporary root
and exposed the Git filename-probe defect. After its regression fix, the complete
run used the documented short tox-owned temporary root with three pytest workers
and `RELAY_TEST_COVERAGE=false`. Hosted Linux CI supplies full branch coverage.

The final wheel contains the exact updated `relay/vcs/commits.py` bytes and the
compiled checklist focus fix. Raw reports, traces, screenshots, and build outputs
remain outside the repository. No owner review documents were changed.

Wheel: `relay_app-0.0.3.dev20261015134856-py3-none-any.whl`.
Its SHA-256 is:

```text
ebff104829ff6e8470248c434f85186ffa23777a9d8a16bc801fba5f947c6a41
```

## Verification limits

This is automated Windows verification. The latest authenticated Windows
provider evidence remains the [2026-10-14 Codex retest](2026-10-14-windows-relay-fixes.md).
Live execution of the other four providers on Windows remains unverified.

Windows pixel baselines are not present. The eight structural visual checks run
natively on Windows; the 21 pixel-comparison cases use the existing hosted Linux
baselines. Hosted CI also runs the complete supported OS/Python matrix.

The PR remains open and unmerged at the owner's request.
