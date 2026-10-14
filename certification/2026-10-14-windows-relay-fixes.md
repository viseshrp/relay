# Relay Windows bug fixes and retest

Date: 2026-10-14. R1-R4 fixed and verified on Windows.

Relay is the subject of this test. SuspendIt provides a real repository for
agent work, owner waits, command execution, Git isolation, and monitoring.
The [initial report](2026-10-14-windows-suspendit.md) preserves the four defects
and their original evidence.

The subsequent [full Python follow-up](2026-10-14-windows-python-suite.md)
passes the Windows Python 3.14 gate and records its capability/platform skips.

## Fixes and live results

1. R1: resolving a job or step name now commits a masked
   `node.display_name_changed` event with the saved name. The monitor's state
   cursor advances; resolving the same masked name again is a no-op. All seven
   names appeared in the live run without pausing or manually refreshing it.
2. R2: ACP terminal-output metadata now retains only the known public text and
   exit-code fields. The browser appends deltas exactly, including repeated
   fragments. The live diagnostic printed `RELAY_EXPECTED_DIAGNOSTIC` and
   failed with exit code 7; both appeared in expanded tool details. The run
   retained 4,093 tool events with zero empty summaries.
3. R3: saving a workflow refreshes its inventory alongside the saved source.
   The live picker and sidebar immediately showed the new workflow name.
4. R4: redispatching a suspended coordinator resumes the run when no waiting
   or failed nodes remain. Answering the live wait committed `run.resumed`
   before the next command started; the browser showed In progress during it.

The changes preserve the pinned ACP SDK, exact model selection, provider
permissions, monitor read queue, pagination bounds, and retained owner data.
No database migration or dependency version change is required.

See the [completed run](2026-10-14-windows-relay-fixed.png),
[failed-tool details](2026-10-14-windows-relay-diagnostic.png),
[resumed status](2026-10-14-windows-relay-resumed.png), and
[structured evidence](2026-10-14-windows-relay-fixes.json). The JSON includes
source-file hashes, retained run/attempt state, public diagnostic markers,
package hashes, and four memory-measurement summaries. Raw process samples
remain in isolated storage; the record lists their original file hashes.

## Initial regression checks

Five new Python cases reproduced metadata and wait-status defects before the
fixes and passed afterwards. A wire-level fake-provider exchange also
preserved terminal deltas and the failed exit code through ACP.

| Check | Windows result |
| --- | --- |
| Provider, monitor, and Actions runtime tests | 149 passed |
| Script/file boundary tests | 51 passed, 1 existing capability skip, 1 known blocked case deselected |
| Native tox/reporting probe tests | 15 passed, including successful and intentionally failing serial lanes |
| Authoring, activity, controls, presentation, monitor boundaries, and serial reads | 38 browser tests passed |
| No-login setup and navigation | 4 browser tests passed |
| Frontend monitor unit tests | 16 passed |
| Frontend build-script and expression checks | 1,036 passed, 5 declared skips |
| Types, editable frontend build, lint, formatting, and `make check` | Passed |
| Wheel/source build, Twine, and distribution content | Passed |
| Fresh installed wheel without Node or npm on PATH | Auth, HTML, and compiled JavaScript returned HTTP 200 |

The full Python 3.14 tox run collected 2,952 cases: 2,912 passed, 37 skipped,
and three failed. Two failures came from nested pytest probes choosing the
user folder as their root and scanning temporary directories that other tests
were removing. Giving those probes the repository's pytest configuration
fixed them; all 15 probe tests passed on rerun.

That run's remaining failure was
`test_subject_and_product_links_are_rejected`: this account cannot create
Windows symlinks (`WinError 1314`). Its focused script check excluded that
already-recorded failure.

The [full Python follow-up](2026-10-14-windows-python-suite.md) fixes the
fixture, adds real Windows junction coverage, and fixes the nested pytest
collection race. One fresh complete run passed 2,916 tests and recorded 38
capability/platform skips; all 2,954 cases were verified exactly once. The
failed run above remains historical evidence. Suite-wide coverage was
explicitly disabled. Other Python versions, operating systems, and Windows
visual baselines were not exercised.

## Additional Windows findings

- R5, fixed: the built-in Python shell inherited the legacy Windows output
  encoding. Printing Unicode crashed with `UnicodeEncodeError`. Its argument
  vector now includes `-X utf8`; preview and execution share that planner.
  A new subprocess test failed before the fix and passed afterwards. The
  browser test also saved and executed its Unicode Python script successfully.
- Two existing browser assertions compared Windows paths with JSON-escaped
  text. They now compare parsed fields or the expected JSON string. Both
  passed in the final 38-test run.
- Windows installs `tzdata`, whose license is labeled `Apache-2.0`. The
  license check lacked that SPDX spelling. Its installed license text was
  verified; the allow-list now accepts that name for the already-authorized
  Apache 2.0 license. `liccheck` and the full quality gate passed.
- This host's first `bash.exe` is the WSL launcher. Selecting installed Git
  Bash in each test process PATH made all 11 Actions runtime cases pass.
  The global PATH is unchanged.
- W1 from the initial report remains an external Codex patch-tool finding.
  No Relay change attempts to alter the provider sandbox or file permissions.

## Live Windows retest

- Windows 11 Home 10.0.26300 x64; Python 3.14.7; Node 24.12.0.
- Relay branch: `feat/windows-dogfood-fixes`, based on
  `391ca00cee606e78ce874d9fbd3d2e464d4677fd`, with local uncommitted fixes.
- Codex ACP 2.2.2, exact model `gpt-6.1-sol`, provider permissions unchanged.
- Isolated storage and adapter under `%TEMP%/relay-windows-20261014`;
  normal owner storage is outside the test.
- Run: `4f247e7e-cedc-4b46-aca8-5ef368c07649`, succeeded at 13:33:38 EDT.

SuspendIt remained a side effect of Relay validation. The agent reused the
Windows memory-test improvement via commit `6f6439c` and added a PowerShell
quick-start to `docs/TESTING.md` in commit
`f074fb361d6eeda40b6a9aaca21b44ea2bd30826`. Relay's later command steps
independently passed quality, all 120 unit/integration tests, packaging, and
all four Windows memory regressions. The run worktree is clean and retained.
SuspendIt's source checkout remains on its original main commit; nothing was
pushed or merged.

Relay's distributions were built from a disposable copy of the current
tracked sources, preserving the running app's assets. The Git-free copy uses
the documented `0.0.0` fallback version; these are local smoke artifacts.
A fresh wheel installation served the application with Git available and
Node/npm absent from PATH. That smoke server was stopped and its children
confirmed gone.

The editable install was refreshed with `uv sync --frozen`. The isolated live
instance was restarted with the final code and rebuilt frontend; the saved
successful run still loads at `http://127.0.0.1:7845/`. Its browser tab remains
open for review. At evidence capture, Relay's index was unchanged and the
fixes and evidence were local.
