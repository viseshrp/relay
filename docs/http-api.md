# HTTP API

Relay exposes this API only through `relay up` on a loopback address. The
browser uses ordinary Django session cookies. It does not send bearer tokens,
and the API is not a remote-service contract.

## Authentication and CSRF

The installation has one owner. `GET /api/auth` reports whether onboarding is
complete, reports the current session, and sets the CSRF cookie. The three
authentication actions are:

| Method and path | JSON body | Success |
| --- | --- | --- |
| `POST /api/auth/onboard` | `{"username":"owner","password":"..."}` | `201`; creates the only owner and signs in |
| `POST /api/auth/login` | `{"username":"owner","password":"..."}` | `200`; starts a session |
| `POST /api/auth/logout` | `{}` | `200`; ends the session |

Onboarding accepts no default password and fails with `409` after an owner
exists. Every project, workflow, agent, run, control, artifact, and cleanup
route requires an authenticated owner session. An unauthenticated request gets
`401 authentication_required` instead of a redirect.

Every `POST` uses `Content-Type: application/json` and must send the Django CSRF
cookie value in `X-CSRFToken`. A missing or expired token gets
`403 csrf_failed`. For example, if the cookie is `relay_csrftoken=abc`, the
request header is `X-CSRFToken: abc`.

## Projects and workflows

| Method and path | Request | Success |
| --- | --- | --- |
| `GET /api/projects` | none | `200 {"projects":[...]}` |
| `GET /api/projects/current` | optional `?project={id}` | `200 {"project":...}`; defaults to the served repository |
| `POST /api/projects/open` | `{"path":"/repo"}` | `200 {"project":...}` |
| `POST /api/projects/relink` | `{"old":"/old","new":"/new"}` | `200 {"project":...}` |
| `GET /api/workflows` | optional `?project={id}` | `200 {"workflows":[{"key":"review.yaml","name":"Review"}],"project":...}` |
| `POST /api/workflows` | `{"key":"review","holder":"tab-id"}`; optional `yaml`, `name` | `201`; creates a validated workflow without overwriting an existing file |
| `GET /api/workflows/<key>/prompt?reference=prompts/review.md` | — | Local instruction text and `base_hash`; limited to the selected project's prompts folder |
| `POST /api/workflows/<key>/prompt` | `holder`, `reference`, `text`, `base_hash` | Creates or saves instructions; requires the workflow lease and rejects stale edits. Use `null` for a new file's hash |
| `GET /api/workflows/{key}` | none | `200 {"yaml":"...","draft":null,"base_hash":"..."}` |
| `POST /api/workflows/{key}/draft` | `{"yaml":"...","base_hash":"...","holder":"tab-id"}` | `200 {"draft":...}` |
| `POST /api/workflows/{key}/save` | `{"yaml":"...","base_hash":"...","holder":"tab-id"}` | `200 {"ok":true}` |
| `POST /api/workflows/{key}/lease` | `{"holder":"tab-id"}` | `200 {"lease":...}` |

Workflow keys use relative POSIX segments below `.relay/workflows/`; `review`
resolves to `review.yaml`, while `nested/review.yml` keeps its explicit suffix.
Empty segments, backslashes, `.`, and `..` are rejected. Draft autosave
preserves invalid YAML and labels it `invalid`. Save validates the complete
workflow and its referenced prompts and subworkflows before an atomic file
replacement. Draft and Save reject a missing, expired, or differently held
editor lease.

Workflow reads, creation, editor writes, configuration probes, and run launches
accept `?project={id}` to bind the request to a registered project. Omitting it
preserves the served repository as the default. Selecting a project never
changes another browser's project. `POST /api/projects/open` also accepts
`"initialize":true` to create the blank `.relay` surface in a Git repository.
Creation without `yaml` writes a blank version 1 workflow. Its bytes remain
uncommitted until the owner commits them.
New workflow and instruction paths reject Windows device names, reserved
characters, and trailing spaces or dots on every operating system. For example,
`NUL.yaml` and `draft:notes.md` are rejected; `nested/review.yaml` is accepted.

Workflow document responses include their `project` and a `warnings` array for
`exists` outputs. These warnings explain boolean-only handoffs; they do not
rewrite the workflow or grant permission to pass a human gate.
Warnings from transitive child workflows include their source `workflow_key`.
Repeated references to the same child do not duplicate its warnings.

`base_hash` is the SHA-256 of the exact saved UTF-8 bytes. For example, loading
bytes `version: 1\nname: A\nnodes: {}\n` returns their hash; Save with that hash
succeeds only while those bytes remain on disk. A stale hash returns `409` and
does not overwrite the newer file. A lease lasts 60 seconds. The same holder
renews it; another holder gets `409` until expiry.

## Agents and runs

| Method and path | Request | Success |
| --- | --- | --- |
| `GET /api/agents` | none | `200 {"agents":[...],"preferences":[...],"registry":...}` |
| `POST /api/agents/{agent-id}/models` | `{}`; optional selected project query | `200 {"models":[{"value":"exact-value","name":"Display name"}]}` from a fresh probe of one tool |
| `POST /api/agents/{agent-id}/configuration` | `{"model":"exact-value"}` | `200` configuration object below |
| `POST /api/runs` | launch object below | `201 {"run_id":"..."}` |
| `GET /api/runs` | optional query below | `200 {"runs":[...],"next":...}` |
| `GET /api/runs/{id}` | `?collection=nodes\|interactions&since=0&limit=200` | `200 {"run":...,"next":...}` |
| `GET /api/runs/{id}/events` | `?since=0&limit=100` | `200 {"events":[...],"next":...}` |
| `GET /api/runs/{id}/artifacts` | `?since=0&limit=200` | `200 {"artifacts":[...],"next":...}` |
| `GET /api/artifacts/{id}` | none | `200` file download |
| `GET /api/artifacts/{id}/preview` | none | `200 {"text":"...","truncated":false,"previewable":true}` |
| `GET /api/runs/{id}/changes` | none | `200` committed diff preview with `text`, `truncated`, `source_commit`, `recorded_head` |

Configuration discovery requires owner authentication and CSRF protection. It
probes only the named installed tool, proves the exact model, and returns
`agent_id`, `model_value`, `effort`, and `permission_mode`. Each selector contains
`config_id`, `name`, `current_value`, ordered `choices` with `value`, `name`, and
`description`, and a `transport`. An unavailable selector is `null`.
The response is advisory; reading it creates no run and sets no effort or mode.
Unsupported explicit values produce `agent_configuration_error` with HTTP 422
during launch preflight. Existing model and authentication errors keep their
public codes. Saved node options are described in
[Workflows](workflows.md#agent-nodes).

A launch body has this shape:

```json
{
  "workflow_key": "review",
  "inputs": {"target": "api"},
  "model": "exact-provider-value",
  "cleanup_policy": "clean_on_success",
  "entry_point": "root.review"
}
```

`model`, `cleanup_policy`, `entry_point`, and `project_id` are optional. If
`project_id` is supplied, it must match the request's selected project; a
mismatch returns `400 config_error` before creating a run. Launch validates the
workflow tree, inputs, clean Git state, declared entry-point artifacts, and all
exact-model routes before creating a run. Independent route failures are
returned together. A successful preflight atomically records the run and
snapshot, creates `relay/run/{run-id}` in an isolated worktree, and durably
dispatches eligible nodes.

Run history accepts `project`, `status`, `since`, and `limit`. `since` is the
opaque run cursor returned as `next`; `limit` is clamped to 200. Event `since`
is the last numeric event ID already consumed. Event pages are ordered by ID,
contain at most 200 events and 1 MiB, and can be replayed without gaps by using
each returned `next` value. Numeric event cursors must fit Relay's nonnegative
database integer range. The live SSE route emits the same event shape and uses
each event ID as its replay cursor. The initial connection may use
`GET /api/runs/{id}/stream?since=17` to start after event 17. On reconnect,
`Last-Event-ID` takes precedence over `since`; omitting both starts at zero.
Both cursors must fit the same nonnegative database integer range.

Run detail pages one collection at a time. `collection=nodes` is the default;
`collection=interactions` returns permission, elicitation, and wait records.
Both use the last numeric record ID as `since`. Stable run and snapshot
metadata accompanies every page. Node pages are monitor summaries; complete
provider and command output remains available through the event history.
Run detail also includes `event_cursor`, the highest event ID read in the same
database statement as its run status, before the node or interaction page.
The browser retains older replayed output but applies state changes only after
this lower bound, including events fetched during initial loading. Before
closing a terminal stream, it confirms the current run state. An old terminal
event cannot close a stream for a run that was later retried.
Run metadata includes the registered `project`. Each node includes captured
`dependencies` (scope paths), `controls` (`target` and `label`), and
`parent_scope`. These fields come from that run's frozen node definitions,
including concrete loop and child scopes, rather than today's editable YAML.
Artifact pages use the same numeric cursor rule. The browser merges pages by
record ID, so loading another page cannot duplicate an item.

For interaction pages, `pending=true` filters before pagination. A positive
`interaction={id}` selects that exact request within the run, including an
answered request. It cannot expose another run's interaction. Older clients
can continue reading the unfiltered collection.

Review previews read at most 256 KiB plus one byte for truncation detection.
UTF-8 text is returned as inert JSON; binary, non-UTF-8, and NUL-containing
artifacts return `previewable:false`. Artifact downloads remain byte-exact.
Diffs use the captured source commit and protected recorded head with Git's
external diff and text-conversion hooks disabled. They exclude uncommitted
changes, which remain in retained attempt evidence.

## Provider and cleanup events

Every event page row contains `id`, `type`, `version` (1), `source`, `ts`, and
`payload`. SSE sends that JSON object as `data`, its type as `event`, and its
numeric ID as `id`. Attempt payloads also contain `scope_path` and
`attempt_number`; run cleanup payloads have no attempt fields.

| Type | Source | Payload |
| --- | --- | --- |
| `run.cleanup_succeeded` | `system` | `{"worktree_state":"removed"}` after successful worktree removal. |
| `run.cleanup_failed` | `system` | The Relay error envelope (`code`, `message`, `context`, optional `next_action`) plus `"worktree_state":"cleanup_failed"`. The run remains succeeded. |
| `agent.provider_event` | `agent` | ACP uses `{"content":...}` for visible non-text content or `{"update":...}` for command, mode, configuration, session, and usage updates. Antigravity uses `{"event":...}` for a malformed step update or `{"text":"..."}` for raw stdout. |
| `agent.result` | `agent` | Antigravity's result object with `response` and `structured_output` omitted. Agent response deltas use `agent.message`. |
| `agent.cleanup_warning` | `agent` | `{"message":"The ACP session may remain in the agent's history."}` when session close fails. |
| `agent.turn_started` | `agent` | One-based `turn` for a prompt in the current session. Message boundaries remain separate between turns. |
| `resource.cleanup_succeeded` | `system` | `{"removed":0}` or the number of marked attempt allocations removed during terminal cleanup. |
| `resource.cleanup_failed` | `system` | A recoverable `message`; cleanup failure leaves the run's result intact. |

ACP text events preserve an optional `message_id`. Native Antigravity step
identities combine the conversation and step index; conversation `abc`, step
3 becomes `abc:3`. Tool events keep `tool_call_id` when available. Original
event parts and IDs remain available even when the browser assembles them.

Provider payloads above the 32 KiB normalization budget split into ordered
parts. A string field (`text`, `summary`, or `chunk`) keeps its other fields
and gains one-based `part` and total `parts` counts. Other large payloads become
`{"chunk":"...","part":1,"parts":2}` records containing consecutive slices
of the original JSON text. Join those chunks before parsing the JSON. Relay
reserves the remaining persisted-event budget for scope and attempt metadata;
it splits on Unicode character boundaries and accounts for JSON escaping.

## Controls

Run cancel and rerun keys are stored in an indexed event column; duplicate
requests do not scan event payloads. Canceling a run still preparing its
worktree (`pending`) or awaiting restart reconciliation (`interrupted`) returns
`stale` (409). Retry with a new key after preparation or reconciliation finishes.

| Method and path | JSON body |
| --- | --- |
| `POST /api/runs/{id}/cancel` | `{"idempotency_key":"cancel-1"}` |
| `POST /api/attempts/{id}/permission` | `{"idempotency_key":"p-1","decision":"option-id"}` |
| `POST /api/attempts/{id}/elicitation` | `{"idempotency_key":"e-1","value":{...}}` |
| `POST /api/attempts/{id}/wait` | `{"idempotency_key":"w-1","value":...}` |
| `POST /api/runs/{id}/rerun-node` | `{"scope_path":"root.failed","idempotency_key":"r-1"}` |

Control results are distinct and stable:

| Result | HTTP status | Meaning |
| --- | --- | --- |
| `accepted` | `202` | Durable request created for the current attempt |
| `already_applied` | `202` | The idempotency key or requested terminal state already exists |
| `stale` | `409` | The answer targets an attempt that is no longer current |
| `invalid` | `422` | The body or interaction kind does not match a pending request |

An idempotency key belongs to one exact attempt. Reusing `p-1` for the same
permission returns the first outcome; it cannot answer a later attempt. Keys
must contain 1 through 200 characters; longer values return `invalid` before
Relay changes run or attempt state. A permission decision must name an offered
option, and an accepted ACP elicitation value must be a JSON object; mismatches
return `invalid` without reaching the live agent session.
All answer bodies may include a positive `interaction_id`. It must match the
exact pending interaction of this attempt. Permission and elicitation answers
may also include a nonempty `feedback` string. The answer resolves that request;
after the current ACP turn ends, feedback is submitted in another prompt to
the same session with the same model, options, and deadline. It never grants
permission or changes static prompt files. A declined permission stays declined;
feedback can request an alternative. Canceling the attempt prevents another turn.
Cancellation fans out to every active attempt. Failed-node rerun preserves any
remaining evidence, resets only to the recorded safe head, and creates a new
attempt; a nested selection also reopens only its failed structural parents.
Successful nodes stay complete.
Concurrent rerun submissions for the same run cannot both mutate the retained
worktree. While one request prepares recovery, another receives `409 stale` and
can retry after the active request finishes.

## Cleanup

`POST /api/runs/{id}/resources/clean` accepts `{"confirm":true}` and returns
`{"removed":<count>}`. Only succeeded, failed, or canceled runs are eligible.
Cleanup selects ended attempt IDs before disk work, so a concurrent retry's
new allocation is excluded. It removes only correctly marked run allocations;
unmarked files, symlink targets, worktrees, reports, and credentials stay in
place. Normal attempt completion and terminal run transitions invoke this
cleanup automatically.

`POST /api/data/clean` accepts
`{"scope":"runs|worktrees|branches|all","confirm":true}`. A missing literal
`true` returns `409`. Relay rejects cleanup while the current project has an
active run. Reader worktrees are removed before their primary run worktree,
and all worktrees are removed before branches. Run rows and their retained
artifact directories and ended-attempt scratch allocations are removed only
for `runs` or `all`. Unmarked scratch files remain. `all` also empties
Relay process logs and rotations in place, keeping their `Relay process log`
first line, so open append handlers can continue writing. Files without that
line are left alone. Cleanup never changes the launch branch.

## Errors and limits

Every JSON failure has this Relay-owned envelope:

```json
{
  "code": "workflow_validation_error",
  "message": "Workflow validation failed: ...",
  "context": {"workflow": "review"},
  "next_action": "Correct the workflow and try again."
}
```

`next_action` is optional. Third-party exception names, tracebacks, and private
provider fields do not cross the HTTP boundary. Request bodies are limited to
1 MiB. Control payloads are limited to 64 KiB. Reads and event frames are also
bounded so one browser request cannot load unbounded history. Unknown API paths
and unsupported methods also return JSON envelopes rather than the SPA or an
HTML error page.

Run path identifiers are UUIDs; attempt and artifact identifiers are positive
integers. A malformed or unknown identifier returns the same Relay-owned `404`
response and does not reach a state-changing service.
