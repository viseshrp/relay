# CI execution and test completeness

Relay runs the complete Python matrix and browser suite on standard
GitHub-hosted runners. Native tox commands, pytest-xdist, and Playwright
provide execution and reports. Small validators check complete execution.

## Python matrix

Main and Release run Python 3.10 through 3.14 on Linux, macOS, and Windows.
Both Node 20 and Node 24 remain available to every local-action integration
test. Windows 3.10 retains managed CPython 3.10.19; other jobs use
setup-python. Each job reports its Python and SQLite versions.

[tox.toml](../tox.toml) declares collection, serial execution, parallel
execution, coverage reports, and verification as ordinary tox commands.
Native TOML conditions preserve the `RELAY_TEST_COVERAGE` switch. Tox's
`ignore_errors` runs subsequent commands after failures and still fails the
overall environment. Failed execution cannot be hidden by a later command.

Timed SQLite contention, concurrent launch bursts, and process-recovery
cases use the `serial_integration` marker and run serially. Their internal
threads, subprocesses, lock durations, and assertions remain intact. Other
cases use pytest-xdist work stealing with three workers on Linux/Windows
and two on macOS. Worker restarts are disabled.

Each worker owns its database template, Huey queue, environment, provider
transcripts, and temporary repositories. Every test gets a fresh database
copy. Real Git and deterministic provider subprocesses remain enabled.

Linux/Python 3.14 records branch coverage from both lanes and uploads the
canonical XML to Codecov. The other 14 jobs run every test without
suite-wide coverage instrumentation. Sources, exclusions, and thresholds
remain unchanged. Local tox runs collect coverage by default.

### Local execution and reports

Run the supported interpreter matrix:

```bash
make test
```

Use a supported interpreter and explicit workers for a focused run:

```bash
RELAY_TEST_WORKERS=2 uv run tox -e py313 -- tests/test_execution_core.py
```

Set `RELAY_TEST_WORKERS=0` for serial execution of both lanes. Set
`RELAY_TEST_COVERAGE=false` to disable tracing and coverage report commands.
An empty lane is valid for a focused file; an empty overall inventory fails.
Local missing Node runtimes and declared platform skips keep their reasons.
Both Node runtimes are required in CI.

Symlink fixtures report the host capability error when link creation is
unavailable. A separate Windows directory-junction test exercises artifact
subject and product-selection rejection with a real reparse point without
requiring symlink privileges.

Tox resets its own temporary directory before each invocation. Local
reports live in `.tox/py313/tmp/reports` for the example above. CI supplies
a short tox-owned root, `$RUNNER_TEMP/rp`, to avoid extending Windows Git
paths. `RELAY_TEST_TEMP_DIR` overrides this disposable directory; tox resets
its contents. Keep the default for ordinary local runs.

Each lane writes native pytest JUnit XML, including setup and teardown
failures, captured failure diagnostics, test identities, and checkout
identity. Pytest prints its slowest tests with `--durations=20`. The compact
inventory validator rejects missing, duplicated, incorrectly routed,
failed, or unexpectedly skipped tests. Collection and worker failures also
fail tox through their native exit codes. Coverage-enabled runs retain
coverage XML, JSON, and the coverage database in the reports directory.

## Browser preparation and shards

Preparation runs all build-script, expression, unit, and TypeScript checks,
and builds the browser application once. Native Playwright collection
provides inventories for functional, no-login, visual, and unit suites.
Verification checks that four functional shards exactly partition the full
functional inventory.

GitHub Actions invokes Playwright directly on four separate Ubuntu jobs.
Each job downloads the same prepared build and starts its own isolated
Relay server. Playwright uses `--shard=N/4`, one worker per server, zero
retries, and file-level ordering. Snapshot updates are forbidden.

The fourth shard also runs the complete no-login and visual suites in
separate Actions steps. Both steps use `always()` after valid asset setup,
so a functional failure cannot prevent either auxiliary suite from running.
Native step failures remain job failures.

Preparation archives the complete build, including hidden manifests and
compressed files, using tar. It rejects symlinks and special files. Native
`sha256sum --check` verifies the downloaded archive before extraction, and
each shard checks its captured Git commit against its actual checkout.
The isolated server serves these assets through `RELAY_TEST_ASSETS_ROOT`.

Native Playwright JSON reports include checkout metadata. Blob reports
retain traces and screenshots. The compact browser validator reads those
reports and checks every shard, auxiliary suite, unit test, expected test
identity, status, and checkout. Missing, duplicated, interrupted, retried,
failed, or unexpectedly skipped execution fails the aggregate.

The aggregate requires preparation and every shard to succeed. It uses
Playwright's native `merge-reports` command for the combined HTML report,
including trusted reports containing failures. Unit reports remain separate
because they use a different test directory. Successful reports last one
day; failed browser traces and screenshot diffs last seven days.

The verification helper has only two commands:

```text
node frontend/scripts/verify-browser.mjs inventory OUTPUT
node frontend/scripts/verify-browser.mjs verify REPORTS INVENTORY BLOBS
```

It does not execute test suites. Existing `npm test` and
`make test-frontend` still run all their checks. For concurrent local shard
validation, use distinct `PLAYWRIGHT_PORT` and `PLAYWRIGHT_VISUAL_PORT`
values. Each server uses temporary storage and deterministic providers.
Build scratch assets separately from an owner's running application.

## Publication, rollback, and measurement

Main publication still depends on quality, all 15 Python jobs, and the
complete browser aggregate. Release uses the same Python setup and matrix.
Production distributions are built and checked separately from test assets.

The unsharded visual-baseline refresh still generates candidate baselines
and runs the complete browser verification. Main's manual inputs retain
`serial_python`, `cold_cache`, and `refresh_visual_baselines`. Cold-cache
runs disable dependency-cache restoration and saving.

Compare executed identities and covered lines/branches across the same
code and runtime versions. GitHub supplies native job and step timings;
measure workflow creation-to-completion separately to include runner queues.

The acceptance target remains three consecutive complete optimized passes
with a median workflow time at or below 20 minutes, including a cold-cache
pass at or below 25 minutes. Local checks do not establish the complete
OS/Python matrix or certify authenticated provider behavior.
