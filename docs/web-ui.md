# Local web runtime

Relay's browser application controls work in registered local repositories.
It runs on loopback and has no remote deployment mode in Phase 1.

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

If the first authentication request fails, Relay shows the error and a Retry
button. A failed sign-out request also shows its error and can be retried.

## Choose a project and workflow

The project bar stays visible above both views. Choose a registered project,
or use **Open another project** and enter its local Git repository path. Relay
can initialize a blank `.relay` surface there. Each browser keeps its own
selection; changing projects does not change another browser's selection.

**Workflows** sets up stages, instructions, and inputs. **Runs** shows work
already started. The run header names its captured workflow and project,
shows completed steps, and states what happens next. Internal IDs, branch
names, provider JSON, and cleanup controls are under advanced views.

## Author workflows

Choose a saved workflow from the menu, or use **New workflow** to create one
in the selected project. **Add stage** asks for a name and an action. Commands,
agent work, and human reviews have ordinary form fields. The new stage starts
after the previous one; **Start after** changes its dependencies. An empty
workflow explains how to add the first stage.

Advanced workflow settings expose the YAML editor and workflow key. `review`
and `review.yaml` both refer
to `review.yaml`, and nested keys use `/`. Empty segments, backslashes, `.`,
and `..` are rejected. The canvas and CodeMirror edit one eemeli `yaml`
document. Typing valid YAML redraws the graph. Adding, deleting, or configuring
a canvas node rewrites that same document instead of maintaining a second graph
model.

The stage panel covers all six node types. Dependencies are selected by stage
name. Commands have a Program field and one argument per line. For example,
program `git` with arguments `status\n--short` saves
`run: [git, status, --short]`; a line `a b` stays one argument. Relay does not
invoke a shell. An optional advanced field accepts an explicit JSON argument
array. Invalid JSON stays in that field and is not applied.

Agent instructions can be written and saved in the stage panel. They live in
the selected project's `.relay/prompts` folder. Saving checks the loaded file
hash and requires the workflow's editing lease. Unsaved instructions block
stage and project changes, workflow saving, and launch until they are saved.
Use the model menu to select an advertised exact value; **Load available
models** refreshes installed tools. A model read never grants permissions or
changes provider defaults. The exact-value field remains available for a
provider value already known to the owner.

Workflow reads warn about `exists` report outputs in root, loop, and child
workflows. **Retain the report** explains file-retaining selectors and verdict
checks. Warnings never rewrite outputs or answer a human review.

Agent nodes show the effective tools from node, workflow, and owner preferences.
The Agent tools field adds node preferences in selection order. Each tool has
an Effort dropdown for the selected exact model and a Permission mode dropdown.
Both start at **Provider default**, leaving the override absent from YAML and
provider requests. Choosing a value saves it under the node's per-tool
`agent_options`; choosing Provider default removes it.

Choices come from a fresh disposable tool session after model selection. While
loading, the dropdowns are disabled. A failed read shows an error and Retry.
Changing the node's model override resets effort and loads its new choices.
Unsupported saved values stay visible for correction and fail launch preflight.
A tool without a separate selector offers only Provider default. Native
Antigravity effort is included in the exact model slug; choose another exact
model to change it. See [Coding agents](agents.md#effort-and-permission-modes).

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

Switching views, workflows, or projects flushes the recovery draft first.
Requests are serialized so an older draft cannot overwrite a newer one.
Leaving the page with unsaved changes triggers the browser's warning.

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
model value entered by the owner. Advanced start settings select
`clean_on_success` or `retain` and one declared entry point. The form explains
that tools work on a separate branch and pause for owner requests. Launch is
disabled for empty workflows, unsaved changes, or invalid YAML. The server
repeats validation, clean-Git,
artifact, and exact-model preflight before it creates a run.

## Monitor and control runs

The Runs tab lists history for the selected project. The header shows the
current stages, progress, and next action. Pending requests appear before the
graph; failed steps have Show step and Retry step controls. Stage buttons
focus the graph on that step at a readable scale.

The graph uses captured dependencies and control targets, so editing today's
workflow cannot redraw a past run's connections. Connected rows show stage
order and branches. Nested workflows and loop iterations keep their concrete
scope paths; completion junctions join child branches and order iterations.

The monitor combines the SSE stream with paginated database reads:

- Activity joins adjacent text fragments and command stream bytes into readable
  messages, with stage, tool, time, and attempt attribution. Turn, message,
  attempt, stage, and stdout/stderr boundaries stay separate. Split tool JSON
  is assembled before readable summaries are shown. For example, `"Hello "` plus
  `"world\n"` becomes `"Hello world\n"` within one message;
- original events and complete provider payloads remain available under
  Advanced diagnostics and saved files;
- event history loads forward by the last durable event ID, then starts its
  live stream after the last loaded event;
- node, interaction, and artifact lists load bounded pages by record ID;
- pending permission, elicitation, and human-wait records show distinct forms;
- failed nodes expose a manual rerun action;
- retained artifacts expose authenticated download links.

At a human review, instructions and the response requested by the workflow
appear beside retained reports and the committed source-to-run-head diff.
Text previews are bounded to 256 KiB and shown as inert text. Download full
reports when a preview is truncated; inspect the retained branch for a full
large diff. Relay does not guess or submit the approval response.

Tool permission requests require an explicit offered decision. Simple agent
forms have typed fields; complex forms retain a JSON fallback. Optional
feedback is sent into the same live ACP session after its current turn ends.
This does not restart the worker or edit static instructions.

**Link to run** and **Link to request** include the project, run, and interaction.
Reload preserves the selection. A bare app URL restores the last selection.
An already answered request is identified, and current pending requests remain
visible. Answer submission includes the exact interaction ID, so a late
response cannot answer a newer request in the same attempt.

Stop work opens a dialog explaining that completed results remain available.
Confirmation creates one durable, idempotent control request and fans it out
to live attempts. A stale or duplicate answer cannot reach a later attempt. Manual
rerun is available only for a failed run and failed node; Relay preserves
evidence and creates a new attempt. A nested failed node also reopens its failed
loop or subworkflow parents, while successful siblings remain complete. An
interrupted run resumes automatically when `relay up` restarts, also as a new
attempt. Restart recovery never resumes an old provider session; feedback
during a live permission or elicitation pause continues that existing session.
Node completion leaves the live stream open. Only a run-level `succeeded`,
`failed`, or `canceled` event closes it. Interrupted runs keep their stream
open, and an accepted rerun reopens a completed stream without changing the
selected run. Events arriving in one browser frame update history together;
ordered pages merge without sorting the entire history for each event.

## History, artifacts, and cleanup

Relay automatically releases attempt scratch folders and surviving processes.
Terminal runs expose **Retry temporary resource cleanup** under Advanced
diagnostics. This touches only marked attempt folders; it keeps code,
evidence, credentials, and personal browser profiles. See
[Run-owned resources](projects-and-storage.md#run-owned-resources).

History, snapshots, output, interactions, and artifacts remain until explicit
cleanup. Advanced data cleanup selects `worktrees`, `branches`, `runs`, or `all`
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

The initial URL may contain `?since=17` when event pages already include ID 17.
The client keeps the last received ID. Reconnecting with
`Last-Event-ID: 17` returns only rows whose ID is greater than 17; the header
takes precedence over the URL cursor. Reads use the
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
browser connection cancels the async generator. Django's ASGI request context
closes the request's database connections in their owning executor thread.
Paginated history remains available at
`GET /api/runs/{id}/events`.

## Supervisor and shutdown

The parent process owns one heartbeat-backed database lease and supervises two
children:

1. Uvicorn serves Django's HTTP, SSE, and packaged static files.
2. Huey runs with thread workers and a 15-second shutdown timeout.

Press Ctrl+C once to stop. Relay first writes a durable shutdown marker, closes
new-run admission, marks running and paused runs `interrupted`, and sends each active
attempt an `orderly_shutdown` cancellation request. On POSIX, Huey receives
`SIGINT`, its graceful signal. On Windows, Relay does not depend on a console
event that Huey 3.4.0 does not handle; workers observe the durable request and
the parent terminates the consumer within the same bound. A process that misses
the grace is force-stopped. Interrupted attempts in canceling runs settle as
canceled; other in-flight attempts are recorded as interrupted. Attempts that
finish successfully keep their outputs and protected commits, and failed
attempts keep their failure details.

An orderly restart preserves attempt evidence before resetting a writer or
removing a disposable reader worktree. It reopens each interrupted run and
creates a new attempt; it never resumes an old agent session or automatically
retries a failed attempt. A worker process that dies without the shutdown
marker is recorded as `worker_lost` and fails the run instead.
Runs already canceling retain that status and drain to `canceled` or `failed`,
including after restart. Relay never reopens work canceled by the owner.

Startup does not signal PIDs saved by an earlier Relay instance: after a crash
or reboot a PID can belong to another program. Relay logs those unverified
attempt IDs and PIDs for the owner to inspect.

Relay removes the supervisor lease and shutdown marker only after a clean stop.
If startup or shutdown reconciliation fails, retained state and the marker stay
available for the next bounded reconciliation pass. Full trace context is in
the platform-specific `relay-{pid}.log` files described in
[Projects and storage](projects-and-storage.md#central-paths).
