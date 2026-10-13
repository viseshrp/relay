# CI execution and test completeness

Relay runs the complete supported Python matrix and the complete browser
suite on standard GitHub-hosted runners. Parallelism changes where tests run,
while inventories verify that every collected case finishes exactly once.

## Python matrix

Main and Release run Python 3.10 through 3.14 on Linux, macOS, and Windows.
Both workflows install Node 20 and Node 24 and pass their executable paths to
tox. This keeps local JavaScript action tests active on every platform.

The shared runner uses three pytest workers on Linux and Windows and two on
macOS. Each worker owns its Django template database, Huey queue, environment
overrides, provider transcripts, and temporary repositories. Every test still
receives a fresh database copy. Real Git and provider subprocess integration
remains enabled.

Tests that deliberately measure SQLite lock budgets, concurrent launch
bursts, or supervisor process recovery run in a separate serial lane. Their
internal thread and process concurrency remains unchanged. The other tests
run with xdist work stealing. Both lanes execute even if one fails; worker
crashes fail the job without automatic worker restarts.

Both lanes record branch coverage into one job-specific database. Final XML
and JSON reports include both lanes. All 15 environments retain coverage;
the canonical Linux/Python 3.14 report also uploads to Codecov. Existing
coverage thresholds and exclusions remain unchanged.

### Local execution and reports

The ordinary supported-interpreter command remains serial:

```bash
make test
```

Run the complete suite with explicit parallelism and retained reports:

```bash
uv run python scripts/run_python_tests.py \
  --workers 2 --reports-dir /tmp/relay-python-results
```

Pass test paths after the options for a focused run. Use `--workers 0` for a
complete serial reference. Local missing Node 20/24 runtimes remain visible
as skips; CI requires both runtimes. Declared platform skips and unavailable
symlink privileges retain their reasons.

Reports contain the full inventory, selected lane identities, setup/call/
teardown outcomes, JUnit XML, coverage XML/JSON, and JSON/Markdown summaries.
The runner rejects missing or duplicated cases, collection errors, incomplete
phase reports, failed tests, and unexplained skips. A failed lane cannot be
hidden by a later passing lane.

Each invocation creates a fresh, short pytest storage root under
`RUNNER_TEMP` when available, with separate directories for collection and
each lane. This avoids extending Windows Git paths with the default user
temporary directory. Failed runs retain that root and record its location
in the summary. Failed test reports also retain bounded Git command stderr;
passing tests do not expose that diagnostic output.

Tox forwards `RELAY_TEST_WORKERS` and `RELAY_TEST_REPORT_DIR`. Without an
explicit report directory, tox stores reports beneath each environment's
temporary directory and also maintains the legacy root `coverage.xml`.
Ordinary direct pytest commands continue working without CI reporting.

## Browser preparation and shards

Frontend preparation runs the complete Node build-script and expression
suite, the frontend unit suite, TypeScript checks, and one browser build.
Lint and formatting remain in the quality job. Existing local `npm test`
and `make test-frontend` still run their complete checks.

Preparation collects functional, no-login, visual, and unit inventories and
verifies that four functional shards exactly partition the functional
suite. Every shard uses a separate Ubuntu machine and isolated Relay server.
Playwright keeps one worker per server and file-level ordering. The fourth
shard also runs the complete no-login and visual suites, even after a
functional failure.

Preparation archives the build, including hidden manifests and compressed
companions. A SHA-256 manifest identifies the archive, every asset, and the
actual checkout commit. Each shard verifies those bytes before using
`RELAY_TEST_ASSETS_ROOT` to serve the prepared application.

The `browser-tests` aggregate requires preparation and every shard to
succeed. It verifies the inventories, checkout identities, outcomes, and
report completeness before merging browser reports. Missing, duplicate,
interrupted, retried, unexpectedly skipped, or failed cases fail the gate.
The frontend unit report is verified separately and retained with
preparation because it has a different Playwright test directory.
Trusted reports from failed tests still contribute their blobs to the
merged HTML report. Their failures remain aggregate gate errors.

Successful preparation and reports are retained for one day; failed
browser traces and screenshot diffs retain the existing seven-day policy.
The functional, login, visual, and unit reports have distinct output paths.

### Local shard validation

The browser helper exposes these commands:

```text
node frontend/scripts/ci-browser.mjs inventory
node frontend/scripts/ci-browser.mjs prepare-assets
node frontend/scripts/ci-browser.mjs verify-assets
node frontend/scripts/ci-browser.mjs unit
node frontend/scripts/ci-browser.mjs run
node frontend/scripts/ci-browser.mjs verify
```

Each command rejects missing required arguments. Use the workflow invocations
as complete examples. Set a distinct `PLAYWRIGHT_PORT` for each functional
server when validating multiple shards on one machine. Set
`PLAYWRIGHT_VISUAL_PORT` to isolate the visual server too; its default remains
4176. No validation command reuses an existing server.

Build and serve scratch assets when an owner instance is running. Do not
replace that instance's compiled files to validate CI.

## Publication, rollback, and measurement

Main keeps publication dependent on quality, all Python environments, and
the complete browser aggregate. Release uses the same Python test setup and
runs all 15 matrix jobs with a concurrency ceiling of 15. Production
distributions are built and checked separately from browser test assets.

The manual visual-baseline refresh remains an unsharded Linux workflow path.
It retains generated baselines for review and runs the complete browser
verification. Normal shard execution forbids updating committed snapshots.

Main's manual inputs support validation without changing the test matrix:

| Input | Effect |
| --- | --- |
| `serial_python` | Run every Python environment serially as a reference or rollback |
| `cold_cache` | Skip Python, frontend, and pre-commit dependency cache restoration and saving |
| `refresh_visual_baselines` | Run the dedicated baseline generation and verification path |

For before/after measurements, use the same commit and runtime versions.
Compare executed identities and covered lines and branches, not only total
test counts or coverage percentages. Inspect retained summaries for lane
and test timings; GitHub's job steps show setup and installation time.
Measure workflow creation-to-completion separately from job execution so
runner queue and dependency wait time remain visible.

The acceptance target is three consecutive complete optimized CI passes
with a median workflow time at or below 20 minutes, including one cold-cache
run at or below 25 minutes. These are validation targets, not an established
performance guarantee. A local pass does not establish Windows/Linux
behavior or the full OS/Python matrix.
