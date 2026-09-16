# Local web runtime

Relay's browser application is a local control surface for one repository. It
is not a network service and has no remote deployment mode in Phase 1.

## Start Relay

Run this inside an initialized repository:

```bash
relay up
```

Relay applies database migrations, reconciles durable work, starts Uvicorn and
one Huey consumer, waits for the HTTP API to become ready, and then opens the
browser. Uvicorn 0.52.4 is pinned as the ASGI server and uses its plain `h11`
HTTP implementation. The wheel supplies Uvicorn; an owner does not install or
run a separate web server.

The command accepts these options:

| Option | Default | Meaning |
| --- | --- | --- |
| `--host` | `127.0.0.1` | Loopback address: `127.0.0.1`, `localhost`, or `::1` |
| `--port` | `7845` | TCP port from 1 through 65535 |
| `--workers` | `1` | Number of Huey thread workers |
| `--no-browser` | off | Start without opening the system browser |

Command-line values override `host`, `port`, and `workers` in Relay's settings
file. A second live supervisor or an occupied address fails before another pair
of children starts. Configuration and bind failures exit with status 4. A
child or supervision failure exits with status 5.

Relay binds only to loopback. `--host 0.0.0.0` and non-loopback names are
rejected. IPv6 `::1` is rendered in the browser URL as
`http://[::1]:7845/`; `127.0.0.1` becomes `http://127.0.0.1:7845/`.

## First login

The first browser session shows owner onboarding. Choose the only local owner
username and a password that passes Django's configured password validators.
Relay ships no username or password. Onboarding creates one Django superuser in
a transaction, signs that browser session in, and rejects later attempts to
create another owner.

Later sessions use the same local credentials. Session cookies are HTTP-only,
same-site strict, and expire when the browser closes. Browser actions use a
same-site CSRF cookie and header. Relay does not issue bearer tokens.

## Author workflows

The Author tab opens `workflow.yaml` by default. Enter another key to load a
different file below `.relay/workflows/`; `review` and `review.yaml` both refer
to `review.yaml`, and nested keys use `/`. Empty segments, backslashes, `.`,
and `..` are rejected. The canvas and CodeMirror edit one eemeli `yaml`
document. Typing valid YAML redraws the graph. Adding, deleting, or configuring
a canvas node rewrites that same document instead of maintaining a second graph
model.

The node panel covers all six node types and their shared dependencies. A
dependency field transforms `build, test` into the YAML sequence
`needs: [build, test]`. A command argument field transforms the JSON string
`["python", "-m", "pytest"]` into the equivalent YAML `run` sequence. Invalid
JSON stays in the field and is not applied to the document.

Canvas changes use canonical YAML formatting. Explicit Save compares the
canonical text with the editor text and asks before normalizing collection
style or spacing. For example, `nodes: {}` stays a valid compact empty mapping,
while structurally edited mappings use block formatting. Comments and scalar
values remain part of the parsed document. The dialog warns about formatting
changes because round-trip libraries cannot preserve every presentation choice
after structural canvas edits.

## Drafts, leases, and conflicts

Each browser tab gets an opaque holder ID in session storage. Loading a
workflow acquires its 60-second editor lease; the tab renews the lease every 30
seconds. Draft and Save requests must present that live holder ID. Another tab
can read the file but cannot autosave or replace it until the lease expires.

Changed editor text autosaves to the database after 600 milliseconds without
changing the Git-owned workflow file. Invalid YAML is retained as an `invalid`
recovery draft. Reloading the workflow restores the newest draft and shows its
validation state.

Save validates the complete workflow, prompts, and subworkflows, then replaces
one file atomically. It also sends the SHA-256 hash of the exact bytes loaded by
the tab. If another process changed the file, Relay returns a conflict and
keeps the recovery draft. Reload the saved file, reconcile the draft, and Save
again. A successful Save clears the draft and refreshes the base hash.

## Launch a run

The launch form comes from the loaded workflow's typed `inputs` mapping:

- string inputs use text fields;
- integer and number inputs use numeric fields;
- boolean inputs use checkboxes;
- enum inputs use the declared finite values.

An untouched optional input is omitted so the server can apply its declared
default or resolve it to `null`. Once the owner enters a value, Relay preserves
its JSON type in the launch request.

Cached model observations appear as suggestions, but Relay sends the exact
model value entered by the owner. The form also selects `clean_on_success` or
`retain` and one declared entry point. Launch is disabled while the editor has
unsaved changes or invalid YAML. The server repeats validation, clean-Git,
artifact, and exact-model preflight before it creates a run.

## Monitor and control runs

The Runs tab lists bounded history pages and opens one run monitor. The canvas
shows each materialized scope path with its durable status. Nested loop and
subworkflow instances therefore appear separately. The monitor combines the
SSE stream with paginated database reads:

- provider and command output uses a fixed-row virtualized viewport;
- event history loads forward by the last durable event ID;
- node, interaction, and artifact lists load bounded pages by record ID;
- pending permission, elicitation, and human-wait records show response forms;
- failed nodes expose a manual rerun action;
- retained artifacts expose authenticated download links.

Cancel creates one durable, idempotent control request and fans it out to live
attempts. A stale or duplicate answer cannot reach a later attempt. Manual
rerun is available only for a failed run and failed node; Relay preserves
evidence and creates a new attempt. A nested failed node also reopens its failed
loop or subworkflow parents, while successful siblings remain complete. An
interrupted run resumes automatically when `relay up` restarts, also as a new
attempt. The UI never resumes an old provider session.

## History, artifacts, and cleanup

History, snapshots, output, interactions, and artifacts remain until explicit
cleanup. The cleanup panel selects `worktrees`, `branches`, `runs`, or `all`
and requires a confirmation dialog. Relay rejects cleanup while any run for
the project is active. Worktree removal preserves evidence first, and cleanup
never changes the launch branch. A disposable reader left by an interruption
is removed before its primary run worktree. Run-record cleanup is rejected
until that run's worktree, retained branch, and attempt refs are gone; the
`all` scope applies the safe worktree, Git-ref, then record order.

## Browser support

Relay supports current desktop releases of Chrome, Edge, Firefox, and Safari.
The browser must support modules, `EventSource`, `crypto.randomUUID`, CSS grid,
and session storage. JavaScript and same-site cookies must be enabled. The UI
has responsive single-column layouts for narrow windows, but Phase 1 does not
target mobile browsers or expose a remote web service.

## Live events and replay

The run monitor connects to `GET /api/runs/{id}/stream` with an authenticated
`EventSource`. Each frame has the durable database event ID, the versioned
event type, and one JSON event object:

```text
id: 17
event: agent.message
data: {"id":17,"payload":{"text":"Done."},"source":"agent","ts":"...","type":"agent.message","version":1}
```

The client keeps the last received ID. Reconnecting with
`Last-Event-ID: 17` returns only rows whose ID is greater than 17. Reads use the
indexed `(run, id)` order, at most 100 events per database batch, a 500 ms poll
cadence while a run remains active, and frames no larger than 65,536 bytes.
Provider and command output is split before persistence so visible bytes are
not truncated. A client ignores an event type or version it does not know.

Event types are internal identifiers. Relay defensively converts a carriage
return or newline in a stored event type to a space before framing it. For
example, `agent.message\nignored` becomes `agent.message ignored`; ordinary
`agent.message` is unchanged. The JSON payload still comes from the stored
event row.

The stream closes after replaying all events for a terminal run. A dropped
browser connection cancels the async generator and closes its database
connections. Paginated history remains available at
`GET /api/runs/{id}/events`.

## Supervisor and shutdown

The parent process owns one heartbeat-backed database lease and supervises two
children:

1. Uvicorn serves Django's HTTP, SSE, and packaged static files.
2. Huey runs with thread workers and a 15-second shutdown timeout.

Press Ctrl+C once to stop. Relay first writes a durable shutdown marker, closes
new-run admission, marks active runs `interrupted`, and sends each active
attempt an `orderly_shutdown` cancellation request. On POSIX, Huey receives
`SIGINT`, its graceful signal. On Windows, Relay does not depend on a console
event that Huey 3.4.0 does not handle; workers observe the durable request and
the parent terminates the consumer within the same bound. A process that misses
the grace is force-stopped, and its attempt is still recorded as interrupted.

An orderly restart preserves attempt evidence before resetting a writer or
removing a disposable reader worktree. It reopens each interrupted run and
creates a new attempt; it never resumes an old agent session or automatically
retries a failed attempt. A worker process that dies without the shutdown
marker is recorded as `worker_lost` and fails the run instead.

Relay removes the supervisor lease and shutdown marker only after a clean stop.
If startup or shutdown reconciliation fails, retained state and the marker stay
available for the next bounded reconciliation pass. Full trace context is in
the platform-specific `relay.log` described in
[Projects and storage](projects-and-storage.md#central-paths).
