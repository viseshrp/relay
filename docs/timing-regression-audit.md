# Run monitor timing regression audit

Scan date: 2026-10-11. Base: `main` at `a8c8c37`.

The original failure was a completed or answered run still appearing to wait
for input. The scan traced committed events through SSE delivery, shared HTTP
reads, run detail, job detail, waiting counts, and saved artifacts. It found
two related browser bugs and added 27 regression cases.

## Confirmed bugs

1. A saved-file read captured before completion could arrive after the final
   artifact read and replace the visible list with an empty page. The files
   remained retained on disk. Artifact responses now check the run's read
   generation before updating the list or its pagination cursor.
2. A node page captured before a live pause or resume could arrive afterward
   and restore the previous dispatch state. The pause and resume buttons then
   contradicted the persisted state. Every existing event trigger for a node
   or artifact refresh now invalidates older shared run reads before fetching.

The artifact test and both dispatch tests failed after the late response was
delivered on the original implementation. They pass with the changes in
[useRunWorkspace.tsx](../frontend/src/components/useRunWorkspace.tsx).

## Scan and coverage

| Boundary scanned | Existing protection or coverage | Added cases |
| --- | --- | --- |
| Event page versus terminal status | SSE drains committed tail before closing | Success, failure, and cancellation after empty, partial, and full pages; exact ordered replay across batches (9) |
| Broken stream and reconnect | Cursor validation and replay | Failure after one delivered page, public error redaction, reconnect from the last delivered ID (1) |
| Failed run with automatic recovery | Pending recovery keeps SSE open | Both scheduled and preparing recovery until owner cancellation (2) |
| Client disconnect during live polling | Cancellation propagates through the async stream | Disconnect closes the generator without changing run state or adding events (1) |
| Shared HTTP read lifecycle | Existing independent-subscriber abort test | Invalidated old read finishing after replacement; old abort cleanup; a subscriber arriving before delayed abort; failed-read eviction and retry (4) |
| Actions human wait and run metadata | Existing missing-tail and late-interaction regressions | Late node page after the answer and completion (1) |
| Provider permission and question | Existing waiting indicators for root, loop, child, and repair scopes | Late pending and linked request reads after each kind is answered (4) |
| Owner cancellation | Existing cancel controls and waiting-count checks | Late pending request cannot restore a canceled wait (1) |
| Live dispatch controls | Run state reducer and node collection refresh | Late node page after pause and after resume (2) |
| Run selection | Current-run guards and existing navigation tests | Previous run's late detail cannot replace the newly selected run (1) |
| Saved artifacts | Existing retained artifact delivery tests | Old empty page cannot erase the final artifact list (1) |

The review also inspected job history merging, abortable dashboard reads,
coalesced attention polling, transactional event/state writes, and the
run-detail snapshot cursor. Existing browser regressions already cover initial
loading catch-up, old terminal event replay after retry, and an external retry
reopening a completed stream. Those cases were retained rather than duplicated.

## Test locations and method

- [Server stream tests](../tests/test_web_stream_static.py) exercise the HTTP
  stream and real SQLite-backed state transitions. Only the event-read or poll
  boundary is controlled to force completion, cancellation, or a read failure.
- [Shared read tests](../frontend/e2e/data-layer.spec.ts) control fetch promises
  and subscriber lifetimes directly.
- [Actions wait tests](../frontend/e2e/waiting-requests.spec.ts) cover the current
  workflow dialect's human wait and its run metadata.
- [Run update races](../frontend/e2e/run-update-races.spec.ts) hold real HTTP
  responses, commit the newer state, show it in the browser, then deliver the
  old response. Later repair reads are held so they cannot conceal a stale
  update. Dispatch tests use the real open SSE connection; completion tests
  replay actual persisted event frames through the browser's EventSource.

Execution tests use disposable Git repositories, temporary storage, and
deterministic provider processes. They need no provider subscription or
authenticated AI account. Workflow cases exercise captured plans;
the Actions human-wait case exercises the same monitor with current workflows.

## Validation boundary

Validation ran locally on macOS with Python 3.13.11 and Node 25.3.0.

| Check | Result |
| --- | --- |
| Focused Python stream suite | 44 passed |
| Complete Python suite | 2,818 passed, 13 skipped |
| Focused browser specs | 35 passed |
| Complete functional browser suite | 257 passed |
| No-login browser suite | 4 passed |
| Visual and layout suite | 29 passed; baselines unchanged |
| Frontend build-script and expression tests | 1,020 passed, 5 skipped |
| `make check` and file-scoped pre-commit hooks | Passed |
| TypeScript and scratch Vite build with compressed assets | Passed |
| Documentation links | All 20 Markdown files passed |

A temporary test process removed the server's terminal-tail guard. All six
new empty/partial-page cases then failed, while the three full-page controls
passed. This confirms those tests detect the original lost-tail bug. The
mutation did not edit repository source files.

Tests validate event delivery and browser state consistency. They do not
certify live providers, the full CI OS/Python matrix, or owner runtime state.
Frontend assets were built in temporary storage for the isolated test server.
All 17 pre-existing owner files and all 1,147 served assets matched their
original hashes after verification. The owner's running Relay was preserved.
