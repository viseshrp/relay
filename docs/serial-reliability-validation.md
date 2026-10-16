# Serial reliability validation

This records the serial-first implementation against the owner's approved
plan. The behavioral contracts and write measurements are in
[serial-reliability.md](serial-reliability.md). Validation uses macOS and
Python 3.13.11, disposable repositories and storage, and deterministic
providers. No AI subscription or owner provider account is used.

## Agreed changes to the original Opus plan

The original `SERIAL_EXECUTION_PLAN.md` remains an owner planning file.
These explicit decisions replace its conflicting instructions:

| Original proposal | Implemented decision |
| --- | --- |
| Remove Huey and `huey.db` | Keep Huey, opaque claim delivery, atomic admission, duplicate protection, deferred admission, orphan repair, and `retries=0`. |
| Set SQLite to NORMAL durability | Keep FULL durability on both aliases, with WAL and a 15-second busy timeout. |
| Remove attempt heartbeats | Keep one coordinator per worker; renew unique active attempts and admission locks in one transaction every five seconds. Retry busy renewal for 30 seconds, then stop the worker. |
| Restart an unresponsive worker | No automatic restart. Preserve orderly interruption and unexpected-crash behavior. Process exit must be proved before workspace recovery. |
| Add output buffering if measurements suggest it | Record measurements only. Output buffering remains separate because it changes crash-time output retention. |
| Work in an isolated Git worktree | Use the primary checkout on `main`, as subsequently instructed. Archive the task's extra worktree recoverably. Build into scratch assets and package from a plain temporary source copy. |

Django, SQLite, SSE, one execution thread, transactional web controls, and
the browser redesign remain. No TanStack, Postgres, external service,
run-control intent table, database reset, or migration-history rewrite is
included. Execution concurrency is fixed at one worker.

## Phase and commit map

Commit IDs identify the implementation, including follow-up defects found
during full validation. Documentation changed with its owning contract.

| Phase | Result | Commit |
| --- | --- | --- |
| Carry-forward coverage | Retain the timing-regression branch's server tail fixes and browser races. | `3b0473f` |
| 0 and diagnostics | Controlled write-lock gates, barriers, transaction/wait/hold profiles, suppressed database causes at HTTP, runner, Huey, supervisor, and failed pytest reports. | `204a668`, `81db74b`, `426587a` |
| 1 and 2 | FULL/WAL settings, query-only deferred snapshots, read-first controls, expiry, settlement, and reconciliation. Idle activated triggers do not write unchanged cursors. | `81db74b`, `426587a` |
| 3, heartbeat portion | Shared renewal coordinator, read-only ownership checks, bounded rolled-back database retries, and fatal renewal exhaustion. | `cdd9cac` |
| 4, scheduling portion | Web launch/resume/rerun stop scheduling. One Huey execution thread follows committed scheduling and delivery events, including environment approval. | `4815333` |
| 3, ownership portion | Stale heartbeats cannot release admission. Supervisor checks process creation identities, stops owned trees, proves exit, and blocks uncertain recovery. | `2f3176f`, `426587a` |
| 5 | Expiry, discard, and environment approval append their events in the same transaction as the transition. | `cbf6847` |
| 6 | Coherent bounded monitor API, separate event/state cursors, serial monitor/job reads, stale-response rejection, coherent page rebuilds, bounded backoff, and terminal-tail draining. | `40d508a`, `7fbd5ef` |
| Full-suite follow-up | Recheck control state and lease after lock acquisition; include job metadata in the 1 MiB budget; adapt fixtures to snapshots and worker scheduling. | `de90cd7` |
| Browser follow-up | Keep historical logs lazy, avoid duplicate first-connect reads, recover artifact refreshes coalesced behind old responses, and carry the old timing tests onto monitor snapshots. | `3e6807a` |
| Graph fixture follow-up | Hold a real 14-node graph at a declared owner wait. Preserve the entry/zoom/refresh assertions, assert all 13 edges, and cancel the fixture during cleanup. | `4d029a5` |
| 7 and 8 | Record profiles, run delivery gates, preserve owner state, push a feature ref, and open a draft PR. Windows measurements remain pending CI. | See validation below and PR history. |
| Review follow-up | Wait for fixture lock acquisition, remove obsolete heartbeat writes, cover consumer/process cleanup, and bound page rebuilds with fair, coalesced, cancellable backoff. | `e351333`, `9ee848a`, `947c3ea` |

## Failure proof

The following are observed failures before the fix, or failures after
restoring the faulty behavior for a focused mutation check. Commands use
the final test locations; the diagnostic HTTP test initially lived in
`test_sqlite_reliability.py` before moving to its dedicated module.

| Reproducer | Observed red result | Green coverage |
| --- | --- | --- |
| `uv run pytest tests/test_sqlite_reliability.py -k monitoring_reads -q` | Dashboard and attention reserve the writer and fail under a held SQLite write lock. | Both read through the held writer; zero writer transactions. |
| `uv run pytest tests/test_persistence_diagnostics.py -q` | HTTP cause assertion fails: the suppressed database exception is absent from diagnostic records. | Three diagnostic cases preserve causes, handle nested/cyclic chains, and keep private diagnostic text out of public responses. |
| `uv run pytest tests/test_sqlite_reliability.py -k 'both_connections or empty_control or idle_reconciliation' -q` | Three failures: timeout is 5,000 rather than 15,000 ms; an empty control poll and idle reconciliation reserve the writer. | Both aliases share isolated storage with FULL/WAL settings; empty polling and idle reconciliation reserve no writer. |
| `uv run pytest tests/test_sqlite_reliability.py -k ownership_checks -q` | In-loop ownership checking attempts a write and fails under the held writer. | The ownership check succeeds with zero transactions and autocommit writes. |
| `uv run pytest tests/test_worker_heartbeats.py -k quiet_five_level -q` | Restoring per-loop heartbeat writes makes the real five-level ACP execution fail under a write lock held beyond five seconds. | All five attempts complete after the lock opens. |
| `uv run pytest tests/test_launch_contention.py -k forty -q` | Disabling the selected launch-persistence retry causes the forced-lock, eight-thread burst to fail. | Both ordinary and forced-lock 40-launch bursts retain complete records and unique project numbering. |
| `uv run pytest tests/test_worker_scheduling.py -q` | Web scheduling runs during launch; environment delivery is absent; configuration permits concurrent execution. | Scheduling and serial execution checks pass. The idle worker scheduling case already passed. |
| `uv run pytest tests/test_worker_scheduling.py -k startup_enumerates -q` | Only 200 of 205 active runs are returned at startup. | All 205 are included. |
| `uv run pytest tests/test_worker_handoff.py tests/test_supervisor_lifecycle.py -k 'clock_jump or unverified_surviving or until_worker_exit' -q` | Restoring the stale reaper and bypassing exit proof produces four failures: forward hour/week jumps, a surviving unverified child, and admission release before exit confirmation. | Ownership remains held while the old worker can finalize Git. A negative clock jump already passed and is retained coverage. |
| `uv run pytest tests/test_interaction_events.py -q` | Eight failures cover missing expiry/discard/environment events and failure to roll back their status changes when event append fails. | All eight status/event atomicity cases pass. |
| `uv run pytest tests/test_agent_controls.py -k mailbox_recovery_rechecks -q` | Two failures: an applied control is reconsidered, or a freshly renewed claim is returned to pending. | Both interleavings recheck state, expiry, age, and owner after acquiring the writer. |
| `uv run pytest tests/test_worker_heartbeats.py -k streaming_step_lock_profile -q` | The profile reports one empty transaction and five autocommit writes. | The real 200-message nested ACP run has neither. Per-output-event durability remains. |
| `uv run pytest tests/test_run_monitor.py -k job_pages_include_metadata -q` | A response is 1,049,691 bytes, exceeding 1,048,576. | Every page stays within 1 MiB and 200 attempts while traversing all 1,006 attempts uniquely. |
| `npm --prefix frontend run test:unit -- --grep 'all read and event'` | Removing the `seen > version` rule makes the interleaving test fail. | All 240 ordered read/event interleavings pass with the rule restored. |
| Browser stale-snapshot mutation | Replacing `acceptsSnapshot` with unconditional acceptance publishes the injected stale-title marker after a newer event. | The late-response browser cases reject even a briefly visible stale snapshot. |
| Browser artifact-tail regression | An older empty artifact response consumes the queued refresh; the retained `verdict` artifact never appears. | Both present and missing SSE-tail cases recover the artifact from persisted events. |

The new monitor endpoint was initially absent: its first five API tests
returned 404. That is evidence of a new feature gap, not an old production
defect. Snapshot coherence, bounded Unicode payloads, linked answered
requests, and pagination beyond 1,000 records test the new contract.

New coordinator registration, retry-budget, non-busy-error, exhaustion,
query-only-write rejection, and raw OS-tree tests validate the replacement
design. They are not reported as pre-existing failures. Existing stale and
duplicate answers, duplicate delivery, recovery policy, artifact retention,
PID reuse, and orderly-versus-crash tests remain regression coverage.

All mutation sources were restored before the normal checks. Mutation
browser builds used separate scratch assets. Test gates use events,
barriers, real SQLite busy failures, and process output; the intentional
five-second lock duration is not used to guess when a participant is ready.

## Focused green checks

These commands passed on the final behavior, in addition to the complete
suite below:

```bash
uv run pytest tests/test_launch_contention.py \
  tests/test_worker_heartbeats.py tests/test_sqlite_reliability.py \
  tests/test_worker_scheduling.py -q --junitxml=sqlite-profile.xml
# 29 passed; zero-empty and zero-autocommit profile assertions passed.

uv run pytest tests/test_agent_controls.py \
  tests/test_sqlite_reliability.py tests/test_worker_heartbeats.py -q
# 50 passed, including the two control-lease interleavings.

uv run pytest tests/test_run_monitor.py tests/test_web_api.py -q
# 178 passed, including complete job-response byte accounting.

uv run pytest tests/test_retry_effort.py \
  tests/test_persistence_failures.py -q
# 82 passed; fixtures exercise worker scheduling and both DB aliases.
```

The original failure/green logs remain in the task's local evidence storage.
The measurements are retained as JUnit `sqlite_profile` properties and
pytest report sections. The profile table in
[serial-reliability.md](serial-reliability.md#write-measurements) records the
observed counts, wait times, and hold times.

Focused browser runs passed the serial monitor, stale-response, artifact,
large-finished-run, settings, loading/error/empty-view, interaction, paging,
and initial-resource-read cases. The complete browser gate below is the
delivery result; focused runs are not a substitute for it.

## Full delivery checks

This table records the initial delivery at `241065a`. Review follow-up
validation is recorded separately below.

| Command | Result |
| --- | --- |
| `uv run pytest tests -q` | 2,879 passed, 13 skipped in 790.04 seconds. |
| `make check` | Passed: lockfile, frontend lint/format, all repository hooks, types, security, dependency, license, and generated-help checks. |
| `uv run python scripts/check_doc_links.py README.md CONTRIBUTING.md AGENTS.md docs/*.md` | Passed. |
| `uv run python scripts/check_transition_docs.py` | Passed. |
| `uv run python scripts/check_workflow_examples.py docs/workflows.md` | Passed: 13 guide examples and seven starter workflows. |
| `RELAY_BUILD_ASSETS_ROOT=<scratch-assets> RELAY_TEST_ASSETS_ROOT=<scratch-assets> make test-frontend` | Passed: 280 authenticated (17.1 min), four no-login (18.6 s), 29 visual (2.0 min), and nine monitor unit tests. Node build tests: 1,022 passed, five skipped. |
| `make build` in a plain temporary source copy | Passed: source distribution and wheel; owner assets remain untouched. |
| `make check-dist` in that copy | Passed: Twine metadata and distribution-content checks for both archives. |
| `uv build --wheel <sdist> --out-dir <scratch-wheels>` | Passed: wheel rebuilt from the source distribution. |
| Installed wheel, fresh venv, private Git/config/data/log roots, no Node/npm in `PATH` | Passed: `relay init`, real `relay up --no-browser --no-login`, HTTP 200 for auth/index/compiled JavaScript, clean supervisor exit, and OS proof that both children exited. |

The plain archived source copy has no VCS metadata, so its validation-only
archives use the configured `0.0.0` fallback version. No release version,
tag, package upload, or owner database was changed. All 1,194 packaged runtime
files match the wheel used for the no-Node installed-runtime smoke check.

The first full Python run found fixtures that only blocked the default DB
alias or expected the web request to schedule a retry immediately. Those
fixtures now exercise both aliases and explicitly advance the simulated
worker. Browser fixtures that held the removed collection reads now hold
monitor reads, still observing whether a late response is visibly published.
Workers-field assertions now assert the field's removal. Existing limits,
time bounds, and stale-display assertions were preserved.

A later full browser attempt passed 279 cases and failed before opening the
long-run graph: its fixture expected 14 command subprocesses to finish within
the default five-second assertion window. The trace showed steady progress
through job 10, with no execution error. The fixture now stops at an explicit
owner wait. Both graph tests pass with the same timeout and unchanged
viewport checks, plus assertions for all 14 nodes and 13 edges. This is a
fixture repair, not evidence of a production graph defect. The final full
gate reported above includes this repair.

## Review follow-up

A single read of [CI run 38326398984][review-ci], at `241065a`, confirmed all
five Windows and all five macOS Python jobs passed. Ubuntu 3.12 failed in
the nested-agent test's own `hold_write_lock`, before the held-lock portion
of the experiment began. Its raw SQLite connection used `timeout=0` and
could lose to the accelerated 50 ms renewal thread. The other four Ubuntu
jobs, browser gate, quality gate, and CodeQL passed. Codecov's patch check
also failed: 83.48% against its inherited 86.6% target. The coverage
configuration and thresholds remain unchanged.

[review-ci]: https://github.com/viseshrp/relay/actions/runs/38326398984

The follow-up addresses the review as follows:

1. The lock helper waits up to five seconds for an existing writer before
   holding the lock. A deterministic test first holds that writer elsewhere,
   observes the helper's `BEGIN IMMEDIATE`, and releases the first writer
   only after verifying the helper waits. The old zero-timeout helper fails
   this test with `database is locked`. The nested execution test also waits
   for an actual failed renewal lock acquisition before timing its hold.
2. The unused per-attempt `heartbeat_attempt` adapter is removed. Control
   lease and outage tests now exercise `renew_attempts` and `attempt_owned`.
   Diagnostic coverage exercises the real coordinator under a held writer,
   verifying the native cause is logged while its public error stays generic.
3. Monitor and job page builders stop after four incoherent rebuilds. They
   release the shared queue and retry after 0.5, 1, and 2 seconds. Refreshes
   coalesce during backoff, and owner actions, run selection, and closing a
   job cancel backoff. Exhaustion preserves the accepted view with manual
   retry. The old builders fail both continuously-changing-page unit tests;
   the browser regression also fails against the previous client at
   `241065a`: the open job makes no HTTP read within the five-second
   assertion deadline because the monitor holds the queue. With the fix,
   that browser loads the job during churn and publishes the complete
   refreshed collection after versions settle.
4. The 30-second renewal exhaustion policy is retained and clarified: the
   worker exits, Relay stops, and no automatic restart occurs. Consumer
   lifecycle tests verify normal exit and crashes stop renewal and
   reconciliation. Additional process-tree tests check failed observations,
   exited descendants, PID reuse, and unrelated processes. These are added
   safety coverage, not claims of newly reproduced production defects.
5. The primary checkout stays on `main`; publication advances
   `feat/serial-execution` for the existing draft PR. `origin/main` remains
   unchanged until an authorized merge. No worktree is created.
6. The local, uncommitted `*.md` ignore rule is removed so owner planning
   files are visible again. The unrelated `/test-results` and `/.archify`
   rules remain unstaged. Planning files are neither modified nor committed.

Focused checks passed: 116 Python tests, 16 monitor unit tests, and all nine
serial-monitor browser cases. The full Python suite passed with 2,890 tests
and 13 skips in 850.76 seconds. Local coverage of changed executable lines
is 93.30%; counting every partially covered branch line as uncovered gives
87.83% (498 of 567 lines), above the previous 86.6% patch target. This is a
local measurement, not a replacement for the pending Codecov aggregate on
the follow-up head.

Repository quality checks, new-test file hooks, documentation checks,
distribution builds and content checks, rebuilding the wheel from its
source distribution, and the installed-wheel runtime without Node/npm
also pass. All 152 packaged, non-generated Python source files match the
current checkout, and the build copy matches all 194 frontend source files.
The full frontend gate passes: 281 authenticated browser cases in 17.3 minutes,
four no-login cases in 19.1 seconds, 29 visual cases in 2.0 minutes, and all
16 monitor unit tests. Node build checks pass 1,022 cases, with five skips.
The pre-fix browser mutation and restored green run use a separate port and
asset root; neither changes the owner app or the full gate's assets.

## PR comments and CI follow-up

[CI run 38335763189][review-followup-ci], at `9dff6cb`, passed 14 Python/OS
jobs and both Codecov checks. Patch coverage was 87.99%. Two jobs failed:

- Windows 3.10 exited with native access violation `0xC0000005` during the
  launch burst. The crashing thread was garbage-collecting while parsing
  YAML under coverage instrumentation. The stack alone does not establish
  the native cause. All 15 platform jobs continue to run the full
  suite; only the main Ubuntu interpreter collects the coverage report it
  already uploaded. Other jobs run without a tracer. Coverage thresholds,
  the uploaded report, and supported versions remain unchanged. Local tox
  retains coverage by default and accepts an explicit override.
- The authoring browser test started its five-second completion assertion
  before the launch response. Launch persistence consumed 2.76 seconds,
  and the last accepted snapshot still showed the parent running. The test
  now waits for the successful launch response first. Its completion
  assertion retains the same five-second deadline. Repeating the case
  exposed a separate filename collision before launch: later repetitions
  tried to create the previous repetition's prompt. Each repeat now uses
  its own filename; all five repetitions pass without changing deadlines.

[review-followup-ci]: https://github.com/viseshrp/relay/actions/runs/38335763189

The next [CI run][review-runtime-ci] reproduced the Windows 3.10 native crash
at `b62c9c3` with coverage disabled. Coverage is therefore not a sufficient
explanation or repair. Its ten Linux/macOS jobs passed, including the main
coverage job, and both Codecov checks passed. The failing Windows interpreter
was CPython 3.10.11. CI now selects uv's managed CPython 3.10.19 for that job,
including tox discovery, and reports both Python and SQLite versions. The
full test selection and launch stress cases are retained. The native root
cause remains unproven; final runtime results belong to the PR's current
head, rather than a claimed fix based on the Python stack alone.

[review-runtime-ci]: https://github.com/viseshrp/relay/actions/runs/38343083652

The other CodeQL comments identify six intentional Protocol signatures,
three shared-state assignments read by later calls, and two cancellation
awaits. Those statements remain: lifecycle, scheduling, and disconnect
coverage exercise their behavior. Review replies explain each use before
the corresponding conversation is resolved. The final head's CI result is
recorded on the PR after the checks complete.

Local follow-up checks pass: the full non-instrumented Python 3.10.19 tox
suite has 2,890 passes and 13 skips; 86 backend cases cover renewal, scheduling,
consumer lifecycle, disconnects, and supervisor behavior; both 40-launch
burst cases through the non-instrumented Python 3.10 tox command; and the
authoring browser case. `make check`, frontend lint/format, changed-file
hooks, and documentation links also pass. Tox configuration checks confirm
both the default coverage arguments and the empty override.

## Measurement gate and remaining coverage

The local Phase 7 profile passes its zero-empty, zero-autocommit gates. The
largest individual acquisition wait recorded locally was 102.3 ms during
the deliberately held-lock launch burst. This does not include the total
five-second blockage and does not establish Windows performance.

The review CI result above establishes Windows coverage at `241065a`; it
does not establish Windows performance from local timings. The follow-up
head's Windows/Linux runtime coverage and supported Python matrix remain
pending CI. Twelve optional JavaScript integration cases require installed
Node 20/24 runtimes; a directory-junction
case requires Windows. Live provider certification was not requested.

Initial delivery did not watch or poll CI or automatically rerun failures.
The owner's subsequent PR follow-up request authorizes checking CI through
a green result and repairing its failures. No recurring monitor is scheduled
and the PR is not merged. Output buffering remains a separate change under
the owner's approved scope regardless of these local measurements.

The old plan's line numbers refer to an earlier tree. The corresponding
subjects now live in `db_routing.py`, `db_retry.py`, `heartbeat.py`, the Huey
event follower, the supervisor/process adapters, and `run-monitor.ts` rather
than the proposed replacement worker-loop modules.

Owner preservation checks cover 1,380 planning and served-asset files by
their original hashes. The independently changed owner `.gitignore` remains
unstaged. The owner's app remains on port 17945. The task stays on `main`
without another worktree; publishing uses a separate feature ref pointing
at the validated commits.
