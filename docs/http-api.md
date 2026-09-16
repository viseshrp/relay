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
| `POST /api/projects/open` | `{"path":"/repo"}` | `200 {"project":...}` |
| `POST /api/projects/relink` | `{"old":"/old","new":"/new"}` | `200 {"project":...}` |
| `GET /api/workflows/{key}` | none | `200 {"yaml":"...","draft":null,"base_hash":"..."}` |
| `POST /api/workflows/{key}/draft` | `{"yaml":"...","base_hash":"...","holder":"tab-id"}` | `200 {"draft":...}` |
| `POST /api/workflows/{key}/save` | `{"yaml":"...","base_hash":"...","holder":"tab-id"}` | `200 {"ok":true}` |
| `POST /api/workflows/{key}/lease` | `{"holder":"tab-id"}` | `200 {"lease":...}` |

Workflow keys resolve only below `.relay/workflows/`; `review` resolves to
`review.yaml`. A key such as `../outside` is rejected. Draft autosave preserves
invalid YAML and labels it `invalid`. Save validates the complete workflow and
its referenced prompts and subworkflows before an atomic file replacement.
Draft and Save reject a missing, expired, or differently held editor lease.

`base_hash` is the SHA-256 of the exact saved UTF-8 bytes. For example, loading
bytes `version: 1\nname: A\nnodes: {}\n` returns their hash; Save with that hash
succeeds only while those bytes remain on disk. A stale hash returns `409` and
does not overwrite the newer file. A lease lasts 60 seconds. The same holder
renews it; another holder gets `409` until expiry.

## Agents and runs

| Method and path | Request | Success |
| --- | --- | --- |
| `GET /api/agents` | none | `200 {"agents":[...],"registry":...}` |
| `POST /api/runs` | launch object below | `201 {"run_id":"..."}` |
| `GET /api/runs` | optional query below | `200 {"runs":[...],"next":...}` |
| `GET /api/runs/{id}` | `?collection=nodes|interactions&since=0&limit=200` | `200 {"run":...,"next":...}` |
| `GET /api/runs/{id}/events` | `?since=0&limit=100` | `200 {"events":[...],"next":...}` |
| `GET /api/runs/{id}/artifacts` | `?since=0&limit=200` | `200 {"artifacts":[...],"next":...}` |
| `GET /api/artifacts/{id}` | none | `200` file download |

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

`model`, `cleanup_policy`, and `entry_point` are optional. Launch validates the
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
each event ID as its replay cursor.

Run detail pages one collection at a time. `collection=nodes` is the default;
`collection=interactions` returns permission, elicitation, and wait records.
Both use the last numeric record ID as `since`. Stable run and snapshot
metadata accompanies every page. Node pages are monitor summaries; complete
provider and command output remains available through the event history.
Artifact pages use the same numeric cursor rule. The browser merges pages by
record ID, so loading another page cannot duplicate an item.

## Controls

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
Cancellation fans out to every active attempt. Failed-node rerun preserves any
remaining evidence, resets only to the recorded safe head, and creates a new
attempt; a nested selection also reopens only its failed structural parents.
Successful nodes stay complete.
Concurrent rerun submissions for the same run cannot both mutate the retained
worktree. While one request prepares recovery, another receives `409 stale` and
can retry after the active request finishes.

## Cleanup

`POST /api/data/clean` accepts
`{"scope":"runs|worktrees|branches|all","confirm":true}`. A missing literal
`true` returns `409`. Relay rejects cleanup while the current project has an
active run. Reader worktrees are removed before their primary run worktree,
and all worktrees are removed before branches. Run rows and their retained
artifact directories are removed only for `runs` or `all`. `all` also removes
the current Relay log files. Cleanup never changes the launch branch.

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
