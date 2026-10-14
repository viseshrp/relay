# Full Windows Python suite follow-up

Date: 2026-10-14. Status: passed.

Relay's complete Python 3.14.7 suite passed on Windows 11 Home 10.0.26300 x64.
Tox verified all 2,954 collected tests across both native execution lanes.
The final run had zero failures, zero errors, and no warning summary.

| Lane | Passed | Skipped | Failed/errors |
| --- | --- | --- | --- |
| Serial | 49 | 2 | 0 |
| Parallel, three workers | 2,867 | 36 | 0 |
| Total | 2,916 | 38 | 0 |

The command was `uv run tox -e py314`, with `RELAY_TEST_WORKERS=3` and
`RELAY_TEST_COVERAGE=false`. The full run took 808.84 seconds. Coverage tracing
was disabled, matching the Windows CI lane. Storage and Git repositories
were isolated; providers were deterministic test processes. Installed Git
Bash was selected only in the test process PATH.

## Windows test fixes

`test_subject_and_product_links_are_rejected` now uses the existing
`symlink_or_skip` helper. Its assertions still execute where file-link
creation is supported. This account's unavailable privilege is reported as a
capability skip under the existing inventory rules.

A separate Windows test creates a real NTFS directory junction between owned
temporary directories. Both declared artifact subjects and product selection
must reject that link. The test removes the junction and verifies the target
bytes remain intact. It passed in the complete run. Production path guards
and host permissions were not changed.

The full reruns also exposed a Windows collection race in nested CI probes.
Loading the repository's pytest configuration and setting `--rootdir` did not
bound pytest's ancestor traversal. Probes now also set `--confcutdir` to their
private scratch directory. A global collection plugin rejects directories
outside that root. The old arguments failed deterministically at the user's
AppData directory after this guard was installed. With the traversal bound,
all 15 probe/reporting tests passed with two concurrent workers, and all four
native tox variants passed in the final complete run.

Git checkout identity still comes from the source checkout. Native inventory
verification, both execution lanes, intentional serial failure propagation,
and coverage-enabled probe variants retain their assertions.

## Declared limitations

The 38 skips remain visible in the native reports:

- 22 require unavailable file/directory symlink privileges.
- 6 require the optional local Node.js 20 runtime.
- 6 cover POSIX process groups or incompatible Windows Job Object semantics.
- 4 execute browser-artifact shell commands on Linux CI.

The new junction case provides real Windows filesystem rejection coverage on
this account. This pass covers Python 3.14.7 on this Windows host. Other Python
versions and operating systems were not rerun; offline providers do not
establish live provider certification.

## Retained failed attempts and focused checks

The first full follow-up collected all 2,954 cases and finished with 2,913
passed, 38 skipped, two failed, and one error. Two process-stop deadline
failures coincided with a several-minute native-command stall across the
host; Git outside the tests and ripgrep also stalled. That run reported an
asyncio closed-pipe cleanup warning. The provider and starter-workflow cases
passed on focused reruns and in the final complete run. Shutdown deadlines
and ownership rules were not relaxed.

The second full run passed 2,914 and skipped 38; two CI-probe cases still
failed while other workers removed temporary folders. This showed that
`--rootdir` alone was insufficient. The deterministic collection guard and
`--confcutdir` fix were added afterwards.

Both failed runs retain their original logs and native JUnit reports. The
successful result above comes from one fresh complete run; results were not
combined across attempts.

Focused script/file-boundary checks passed 52 tests with two symlink skips.
File-scoped quality hooks, type checks, and documentation links passed.

See the [structured evidence](2026-10-14-windows-python-suite.json) for all
skip identities, selected regression outcomes, native inventory/JUnit/log
paths and hashes, both failed-attempt summaries, and source-file hashes.
The runtime/test patch hash matches the hash captured before the successful
run. Final reports remain under
`%TEMP%/relay-win-py314-8507a89c/reports`.

The suite ran against local changes on `feat/windows-dogfood-fixes`.
The tested runtime and test files were subsequently committed at
`bc51f3ee1bf088ec75db260e94483b1f5f2f618f`. Their committed patch matches the
pre-run patch hash, and all 18 changed runtime, test, frontend, and dependency
configuration files match their recorded source hashes. The structured record
includes their Git blob identities.

The [earlier Relay fix report](2026-10-14-windows-relay-fixes.md) records the
four product defects and live Windows workflow verification.
