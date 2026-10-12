# Serial execution reliability

Relay keeps Django, SQLite with WAL and FULL durability, Huey, and SSE. One
Huey execution thread runs jobs. The web process commits launches and owner
decisions; the worker schedules their committed changes. No external service,
AI subscription, database replacement, or TanStack dependency is required.

## Implementation and plan decisions

This implementation follows the serial-first execution plan with the owner's
agreed changes. Heartbeats remain, with one coordinator and one renewal
transaction per five-second cycle. Renewal retries SQLite busy failures for
up to 30 seconds, then stops the worker. Database-only launch and control
transactions have a 15-second total retry budget. Git and provider execution
are never replayed by those retries.

Monitoring uses a deferred, query-only database alias. Empty polls and idle
reconciliation read before reserving the writer. Reconciliation runs every
second. A stale heartbeat cannot authorize releasing a live worker's
workspace: the supervisor verifies creation identities, stops owned process
trees, and proves exit first. Unknown ownership blocks recovery. Orderly stop
and unexpected worker loss retain their existing meanings; there is no
automatic worker restart.

Huey's opaque claim delivery, atomic admission, duplicate protection,
`retries=0`, deferred admission, and repair of unstarted delivery remain.
Legacy positive worker counts warn and use one; new API values above one are
rejected, and the browser has no worker-count field. Existing databases and
migration history remain in place.

The browser reads coherent monitor snapshots through one serial queue shared
with open jobs. State events request refreshes; output events append to logs.
Separate state and output cursors prevent output from invalidating state
reads. Older responses are discarded, successful actions invalidate pending
reads, and loaded pages rebuild at one state version. Pages retain the
200-record and 1 MiB limits and can continue beyond 1,000 records. Completion
waits for persisted log tails and pending recovery checks. Existing API
endpoints, linked requests, reconnects, external retries, and artifact merges
remain supported.

## Plan coverage

The issue numbers below refer to the original execution plan. Tests exercise
real SQLite, deterministic provider subprocesses, disposable repositories,
and isolated browser servers.

| Plan issues | Implementation and regression evidence |
| --- | --- |
| I1, I3, I4 | Five-level quiet execution survives a forced write lock beyond five seconds. Nested registrations renew each attempt once in one transaction. Busy exhaustion stops the worker. |
| I2, I12 | Forty launches across eight threads retain complete snapshots and unique project numbering. HTTP, runner, Huey, and supervisor log underlying database causes; failed pytest reports expose suppressed causes. |
| I5, I7, I15 | Control, ownership, settlement, dashboard, attention, job, and monitor reads answer while the writer is held. Snapshot contexts reject writes. Idle reconciliation, including activated triggers, writes nothing. |
| I6, I16 | Both database aliases explicitly use FULL durability, WAL, and a 15-second busy timeout. NORMAL durability was rejected. |
| I8, I9, I17 | Web launch commits no scheduling work. Worker event delivery resumes environment-approved attempts without a web notifier. Huey remains. Startup includes active runs beyond 200. Worker counts above one are rejected or clamped according to interface. |
| I10, I11 | Forward and backward clock jumps cannot release a paused live writer before Git finalization. Killed processes, surviving children, PID reuse, and incomplete Windows tree enumeration retain safe ownership behavior. Automatic restart was excluded. |
| I13 | Expiry, discard, and environment approval commit their interaction events with their status changes. Event-write failure rolls back both. |
| I14 | Pure interleaving, queue, pagination, backoff, and stale-version tests; browser tests force late reads after actions, missing stream tails, changed pages, read failures, and run selection. |
| I18 | Output buffering remains separate. The profile below records the current per-event durability cost. |
| I19 | Existing server terminal-tail and timing regressions are retained from `feat/timing-regression-tests`. |

## Write measurements

A local macOS / Python 3.13 run recorded these values. They measure explicit
SQLite writer acquisition and hold times across all instrumented threads;
failed acquisitions are counted separately. They are observations from one
run, not Windows performance guarantees.

| Scenario | Transactions | Empty transactions | Autocommit writes | Failed acquisitions | Maximum acquisition wait | Maximum hold |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 40 launches, eight threads | 80 | 0 | 0 | 3 | 74.1 ms | 22.4 ms |
| Same launches, forced hold beyond five seconds | 80 | 0 | 0 | 246 | 102.3 ms | 17.5 ms |
| Nested ACP agent, 200 streamed messages | 218 | 0 | 0 | 0 | 0.041 ms | 3.69 ms |
| Five active heartbeat registrations, one renewal | 1 | 0 | 0 | 0 | Measured by test | Measured by test |
| Idle reconciliation / empty control and monitor reads | 0 | 0 | 0 | 0 | No writer acquisition | No writer held |

The forced-hold test uses a short SQLite timeout to exercise rolled-back
retries repeatedly. Its maximum *individual* wait does not include the whole
five-second blockage. Production keeps the 15-second timeout and the same
total retry budget. Run the measurements with:

```bash
uv run pytest tests/test_launch_contention.py \
  tests/test_worker_heartbeats.py -q --junitxml=sqlite-profile.xml
```

Profiles are attached as pytest report sections and JUnit `sqlite_profile`
properties. Unexpected empty or autocommit writes include their call stacks
in the failed test report. The streaming profile first found one empty
settlement transaction and five autocommit session/dispatch writes; those
paths now pass the zero-empty, zero-autocommit gate.

## Failure proof and validation scope

Defect tests were run before their fixes, or with the faulty behavior
restored for a focused mutation check. The checks produced failures for
write-locking monitoring and polls, nested heartbeat renewal, web scheduling,
stale-heartbeat recovery, missing interaction events, the active-run cutoff,
launch retries, and stale browser refresh rules. New API and pagination tests
also cover contracts that did not exist before this change. Existing correct
behavior, including negative clock jumps and duplicate protection, is
reported as retained coverage rather than a newly reproduced defect.

The browser clock mutation removes `seen > version`; the interleaving test
then fails. A separate browser mutation removes the stale-snapshot floor and
must expose a visibly stale pending request. All mutation sources are
restored before normal validation.

Output buffering was not added: it changes crash-time output retention and
needs separate approval and measurements. Local timings do not establish the
Windows result. Windows coverage remains pending until CI results are
available; this change does not watch CI, rerun jobs, or merge itself.
