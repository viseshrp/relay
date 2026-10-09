# HTTP API

`POST /api/workflows/<key>/manage` requires the editing `holder` and accepts
`action`: `rename`, `duplicate`, `disable`, `enable`, or `delete`. File changes
also require `base_hash`; rename and duplicate take `new_key` and an optional
display `name`. Delete requires `confirmed: true`. History and shared prompts
are retained. Workflow inventory includes `disabled`, `last_run`, and
`last_status` when present. Disabled workflows cannot be launched.

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
route requires an authenticated owner session while login is enabled. An
unauthenticated request gets `401 authentication_required` instead of a redirect.

`GET /api/auth` also returns `login_required`, which is `true` by default.
It includes `password_rules`, an ordered list of plain text rules from the
configured password validators before an account exists, or an empty list
afterwards. The browser displays them before account creation; enforcement
still happens on the server. Existing authentication fields are unchanged.
With `relay up --no-login` or the saved `"login_required": false` setting,
`authenticated` reports effective access as `true`, `username` is `local`, and
`owner_created` still reports the actual onboarding state. Relay creates no
user or authenticated session for this access. All owner routes, including
artifact downloads and SSE, accept requests without a session in this mode.
`POST /api/auth/logout` still ends an existing session but reports
`{"authenticated":true}` because the app remains accessible. Restoring login
requires a valid owner session again; existing passwords are preserved.

Every `POST` uses `Content-Type: application/json` and must send the Django CSRF
cookie value in `X-CSRFToken`. A missing or expired token gets
`403 csrf_failed`. For example, if the cookie is `relay_csrftoken=abc`, the
request header is `X-CSRFToken: abc`.

Workflow draft and Save bodies also accept `prompts`, a mapping of local
`prompts/<file>` references to `{text, base_hash}`. Use `base_hash: null` for
a new prompt. One Save publishes the YAML and up to 32 prompt edits together,
rejecting any stale file before publication. The complete prompt edits are
retained with the recovery draft. Edits allow 1 MiB of new prompt text.
`GET /api/workflow-prompts` lists bounded local and global references. The
workflow prompt read endpoint accepts `global:<file>` for read-only preview.

## Workflow language and local automation

These owner routes use the same login and CSRF rules. Select a project with the
normal `project` query parameter. Public create, save, preflight, and launch
accept the Actions jobs/steps dialect. Historical snapshots remain readable.

| Method and path | Purpose and body |
| --- | --- |
| `GET /api/workflow-language` | Relay schema, local contexts/properties, supported fields, and limits |
| `POST /api/workflow-language/validate` | `{yaml, source?}`; pure validation returns `{valid, diagnostics, definition?, sources?}` |
| `GET, POST /api/workflow-bindings` | List or write `{scope, name, kind, value?, source?, reference?}` |
| `GET, POST /api/workflow-environments` | List or write `{name, approval_required, wait_minutes, branches, url}` |
| `POST /api/attempts/<id>/environment` | Approve the exact waiting environment attempt |
| `GET, POST /api/workflow-library` | Inventory/export with `id`, or import `{metadata, yaml, sources}`; `include_project_sources` captures local sources |
| `GET, POST /api/workflow-triggers` | List or activate `{key, event, enabled, allow_writers}` |
| `POST /api/repository-dispatch` | Deliver an activated local `{event_type, client_payload, idempotency_key}` |
| `GET /api/runs/<uuid>/products` | Named artifacts, queue records, and resolved environment links for that run |
| `GET /api/workflow-artifacts/<uuid>/download` | Verified ZIP of a named artifact from the selected project |

Request scopes are `installation`, `project`, or `environment`; environment
writes also provide `environment: <name>`. Saved scope identifiers include the
project identity. Kinds are `variable` and `secret`. Variables are
returned; secret values are write-only. Secret sources are explicit
`environment` or `credential-store`; missing native storage has no plaintext fallback.
Scopes allow 100 bindings of each kind. Names are bounded; values allow 48 KiB.
Environment policies allow 100 names per project, 100 branch patterns each,
waits from 0 to 43200 minutes, and optional HTTP(S) URLs.

Artifact downloads require same-project access and verify retained ownership,
file sizes, and hashes before returning bytes. Expired optional artifacts are
unavailable; required report evidence retains its existing preservation rules.
Automatic activation is an owner operation. Deliveries remain deduplicated in
SQLite, and writing triggers never activate merely by saving YAML.

See [Workflow language](workflows.md) and the
[local language audit](workflow-language-compatibility.md) for event semantics,
credential references, frozen source rules, and expression contexts.

## Home dashboard

`GET /api/dashboard` reads activity across every registered project. It uses
saved database records and neither probes Git or providers nor changes runs.
The normal owner-session requirement, optional no-login access, and public
error envelopes apply.

The response contains `counts` and four pages: `projects`, `waiting`, `active`,
and `recent`. Each page has `items` and `next_cursor`, which is `null` at the
end. Counts are global: registered `projects`, distinct `waiting` runs with
pending requests on waiting attempts, nonterminal `unfinished` runs, and
nonterminal `paused` runs with dispatch paused. Several requests on one run
count as one waiting run. These use the same actionable-request rule as
`GET /api/attention`.

Project items extend the existing project record with `unfinished_count`,
`waiting_count`, and `latest_run`, an existing run summary or `null`. Run
items extend the existing run summary with `project` and `request`. A waiting
item's request contains only `id`, `kind`, and `scope_path`, for opening its
first actionable request. Other pages return `request: null`. Private request
payloads, prompts, and provider output are omitted.

Waiting lists actionable runs. Active lists nonterminal runs without an
actionable request, including paused runs. Recent lists terminal runs ordered
by completion time, falling back to creation time. Project names sort
alphabetically; waiting and active runs sort newest first. Stable IDs break
ties. A run cursor remains usable if that run leaves the requested list.

Query options are `limit` (default 10, maximum 200), `section` (`projects`,
`waiting`, `active`, or `recent`), and `cursor` (the preceding page's UUID).
With a section, the response contains counts and only that page. A cursor
requires a section. `query` filters project names and paths, up to 1,024
characters; run lists and counts remain global. Initial page payloads share a
1 MiB byte budget. Section-only pages have that full budget. Existing project,
run, and attention endpoints keep their payloads unchanged.

## Projects and workflows

| Method and path | Request | Success |
| --- | --- | --- |
| `GET /api/projects` | none | `200 {"projects":[...]}` |
| `GET /api/projects/current` | optional `?project={id}` | `200 {"project":...,"launch_source":{"branch":"main","commit":"..."}}`; defaults to the served repository |
| `POST /api/projects/open` | `{"path":"/repo"}` | `200 {"project":...}` |
| `POST /api/projects/relink` | `{"old":"/old","new":"/new"}` | `200 {"project":...}` |
| `GET /api/workflows` | optional `?project={id}` | `200 {"workflows":[{"key":"review.yaml","name":"Review"}],"project":...}` |
| `POST /api/workflows` | `{"key":"review","holder":"tab-id"}`; optional `yaml`, `name`, `template_id` | `201`; creates a validated workflow without overwriting an existing file |
| `GET /api/workflow-templates` | none | `200 {"templates":[...]}`; the six starter bundles and their typed inputs |
| `GET /api/workflows/<key>/prompt?reference=prompts/review.md` | — | Local instruction text and `base_hash`; limited to the selected project's prompts folder |
| `POST /api/workflows/<key>/prompt` | `holder`, `reference`, `text`, `base_hash` | Creates or saves instructions; requires the workflow lease and rejects stale edits. Use `null` for a new file's hash |
| `GET /api/workflows/{key}` | none | `200 {"yaml":"...","draft":null,"base_hash":"..."}` |
| `GET /api/workflows/{key}/preflight` | optional `?project={id}` | `200 {"clean":true,"blocking_count":0,"allowed_count":0,"files":[],"truncated":false}` |
| `POST /api/workflows/{key}/draft` | `{"yaml":"...","base_hash":"...","holder":"tab-id"}` | `200 {"draft":...}` |
| `POST /api/workflows/{key}/save` | `{"yaml":"...","base_hash":"...","holder":"tab-id"}` | `200 {"ok":true}` |
| `POST /api/workflows/{key}/lease` | `{"holder":"tab-id"}` | `200 {"lease":...}` |
| `POST /api/workflows/{key}/lease/release` | `holder`; JSON or a CSRF-protected form beacon | Releases only this holder's lease |
| `POST /api/workflows/{key}/draft/discard` | `updated_at` from the observed draft | Discards without a lease; rejects a newer draft |
| `GET /api/workflows/{key}/commit` | none | Current `head` and validated untracked source `files`, including `path`, `hash`, and `text` |
| `POST /api/workflows/{key}/commit` | `confirmed: true`, `head`, `hashes` mapping | Commits exactly the reviewed sources; rejects changed bytes, a changed head, or staged changes |

Lease acquisition accepts `takeover: true` for an explicit move between tabs.
`soft_conflict: true` returns a normal `200` response with `lease: null` and
the conflict envelope when another holder is active. Ordinary contested
acquisition keeps its `409` envelope. Takeover invalidates the old holder's
writes; an old release cannot remove the new holder's lease.
Language validation returns every independent field diagnostic up to 100,
including source positions and suggestions for unsupported hosted syntax.

`launch_source` is a fresh read of the selected project's Git branch and commit.
`branch` is `null` for a detached checkout; `commit` is `null` before the first
commit. Reading it does not modify the repository. These fields are additive;
`project` keeps its existing payload. Launch performs its own source capture
and preflight rather than relying on this preview.

Workflow preflight validates the saved workflow, its subworkflows, and local
instructions, then applies the same Git cleanliness rule as launch. It neither
probes agents nor creates a run. Invalid sources return their existing Relay
error envelopes. Each `files` entry has porcelain `status`, root-relative
`path`, optional rename/copy `original_path`, `allowed`, and `reasons`.
Blocking files appear first, with reasons such as `staged`, `modified`, or
`untracked`. Allowed entries explain the exact report, captured source, or
unchanged setup-file exemption. No file contents are returned.

Counts cover every changed file. The preview returns at most 200 entries and
512 KiB of serialized file metadata; `truncated` indicates omitted entries.
The owner can inspect the complete list with `git status`. Reading preflight
does not change files, Git history, the index, or editor leases. Launch repeats
validation and cleanliness checks even after a successful preview.

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
With `template_id`, creation copies the named starter's workflow and prompts
byte-for-byte. It rejects a supplied `yaml`, an unknown template, an existing
workflow, or an existing prompt with different bytes. Identical shared starter
prompts can be reused. All sources validate before copying; a failed copy
removes only its newly created, unchanged files. Gallery records contain `id`,
`name`, `description`, `jobs`, `required_agents`, and schema-defined `inputs`.
New workflow and instruction paths reject Windows device names, reserved
characters, and trailing spaces or dots on every operating system. For example,
`NUL.yaml` and `draft:notes.md` are rejected; `nested/review.yaml` is accepted.

Workflow document responses include their `project` and a `warnings` array for
`exists` outputs. These warnings explain boolean-only handoffs; they do not
rewrite the workflow or grant permission to pass a human gate.
Warnings from transitive child workflows include their source `workflow_key`.
Repeated references to the same child do not duplicate its warnings.

Workflow reads also include `repair_defaults`, containing `max_rounds`,
`max_allowed_rounds`, `fix_instruction`, and `verify_instruction`. The editor
uses these defaults when adding a stage policy; saved custom values remain
part of the workflow. See [Stage repair rules](workflows.md#stage-repair-rules).

`base_hash` is the SHA-256 of the exact saved UTF-8 bytes. For example, loading
bytes `version: 1\nname: A\nnodes: {}\n` returns their hash; Save with that hash
succeeds only while those bytes remain on disk. A stale hash returns `409` and
does not overwrite the newer file. A lease lasts 60 seconds. The same holder
renews it; another holder gets `409` until expiry.

## Agents and runs

| Method and path | Request | Success |
| --- | --- | --- |
| `GET /api/agents` | none | `200 {"agents":[...],"preferences":[...],"registry":...}` |
| `POST /api/agents/check` | `{}`; optional selected project query | `200 {"agents":[...]}` from the same bounded probe as `relay doctor` |
| `POST /api/agents/{agent-id}/models` | `{}`; optional selected project query | `200 {"models":[{"value":"exact-value","name":"Display name"}]}` from a fresh probe of one tool |
| `POST /api/agents/{agent-id}/configuration` | `{"model":"exact-value"}` | `200` configuration object below |
| `POST /api/runs` | launch object below | `201 {"run_id":"..."}` |
| `GET /api/runs` | optional query below | `200 {"runs":[...],"next":...}` |
| `GET /api/attention` | optional `?since={event-id}` | Waiting run count, run IDs, and new completion facts |
| `GET /api/runs/{id}` | `?collection=nodes\|interactions&since=0&limit=200` | `200 {"run":...,"next":...}` |
| `GET /api/runs/{id}/events` | `?since=0&limit=100` | `200 {"events":[...],"next":...}` |
| `GET /api/runs/{id}/job` | `?job=root.check&since=0&limit=100` | `200 {"job":...,"next":...}` |
| `GET /api/runs/{id}/artifacts` | `?since=0&limit=200` | `200 {"artifacts":[...],"next":...}` |
| `GET /api/artifacts/{id}` | none | `200` file download |
| `GET /api/artifacts/{id}/preview` | none | `200 {"text":"...","truncated":false,"previewable":true}` |
| `GET /api/runs/{id}/changes` | none | `200` committed diff preview with `text`, `truncated`, `source_commit`, `recorded_head` |

Finished-run monitors use `events?summary=true`: at most 50 state events and
16 KiB per page, excluding agent output, command output and step summaries.
Oversized state payloads retain bounded identity/status/error fields and set
`summary_truncated`. Ordinary event and job-log reads retain the original
recorded payloads. Explicit full-history loading starts from the earliest recorded event.
`artifacts?visible=true` omits empty internal commit/diff evidence from the
presentation page without deleting retained artifact records or bytes.

Readiness checks require owner access and CSRF protection. Each row contains
`id`, `display_name`, `install_url`, `installed`, `ready`, `error_code`,
`reason`, `cleanup_warning`, exact `models`, `login_command`, and
`login_guidance`. `ready` means the tool returned a usable model inventory;
it does not prove authentication. A structured `agent_auth_error` identifies
a sign-in failure. Other failures keep their distinct codes. Checks do not
send prompts or authenticate. Cached observations remain advisory; launch
and execution still require fresh proof for the selected model and settings.

Configuration discovery requires owner access and CSRF protection. Owner
access is a session when login is enabled, or direct local access when disabled.
It probes only the named installed tool, proves the exact model, and returns
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

`cleanup_policy` additionally accepts `merge_on_success`, inherited from
project/global settings when omitted. It requires a strictly clean checkout
and an attached branch at launch. After all jobs succeed, the run enters
`completing` and fast-forwards the branch captured at launch before removing
the run worktree. Dirty, switched, or diverged targets fail the run and retain
its worktree; no automatic stashing or conflict resolution occurs. Existing
`clean_on_success` and `retain` behavior stays unchanged.
Run records add `merged_commit`, initially `null`. The new `run.completing`
event includes `status` and `branch`; `run.merged` includes `branch` and
`merged_commit`. Success follows durable integration and cleanup. Completion
failures use the existing `run.failed` and Relay error envelopes, including
`failure_summary`; `run_merge_failed` identifies branch or integration errors,
and `dirty_repository_error` identifies target changes. Existing run status
values and event payloads remain valid. Migration `0012_run_merge_completion`
adds the nullable commit field and choices without modifying existing runs.

The workflow preflight endpoint accepts optional `cleanup_policy`, defaulting
to the selected project's effective policy. For `merge_on_success`, every
changed file blocks launch, including usual workflow/report exemptions.
`GET /api/projects/current` adds the resolved `cleanup_policy` for the panel.

`GET /api/runs/{id}/workflow` returns the immutable captured workflow:
`workflow_key`, `yaml`, `truncated`, and `sha256`. The YAML preview is at
most 256 KiB and ends on a UTF-8 boundary. The SHA-256 covers the full source.
The endpoint requires the existing owner authentication and never reads a
mutable authoring draft. Missing runs keep the existing error envelope.

`GET /api/projects/folders` lists directories under the owner's home.
Optional `path` selects a directory, `since` is the last returned name,
and `limit` uses the existing page bounds. The response includes `root`,
`path`, `parent`, `folders`, and `next`. Each folder has `name`,
resolved `path`, and a `repository` hint based on its Git marker. Paths
resolve symlinks before containment checks. Files and their contents are
never returned. Permission and invalid-path failures use Relay envelopes.

Artifact records add `scope_path` and `attempt_number` to identify their
origin. Existing metadata, download routes, cursors, and byte bounds remain
unchanged.

Command stdout and stderr events arrive while a command runs. Chunk
payloads and replay ordering are unchanged; clients merge them by event ID.

Run history accepts `project`, `status`, `since`, and `limit`, plus optional
`workflow`, `branch`, and `query` filters. Workflow and source branch filters
match exactly, with the existing `review` / `review.yaml` workflow alias.
Stored keys remain unchanged. The query matches the captured title, workflow
key, or source commit prefix. Filters accept at most 1024 characters.
`since` is the opaque run cursor returned as `next`; `limit` is clamped to 200.
Event `since` is the last numeric event ID already consumed. Event pages are
ordered by ID and contain at most 200 events and 1 MiB. Use each returned
`next` value to replay them without gaps. Numeric event cursors must fit Relay's
nonnegative database integer range. The live SSE route emits the same event
shape and uses each event ID as its replay cursor. The initial connection may use
`GET /api/runs/{id}/stream?since=17` to start after event 17. On reconnect,
`Last-Event-ID` takes precedence over `since`; omitting both starts at zero.
Both cursors must fit the same nonnegative database integer range.

Run history and detail add `number`, `title`, `source_branch`, and `created_at`.
Numbers increase within each project and remain reserved after deletion. The
title captures the workflow name at launch; the branch records its Git source
when available. Older runs retain their UUID and snapshot bytes. Migration
assigns their numbers in snapshot creation order and leaves their unknown
source branch null. Existing response fields and run cursors stay unchanged.

Run history and detail include `waiting_count`, the number of pending owner
requests attached to waiting attempts. Interaction records add `respondable`
with the same rule. A dispatch pause alone does not create a request or count
as waiting for the owner. Existing status values and control rules stay intact.

`GET /api/attention` counts waiting runs across registered projects and returns
`waiting_count`, up to 200 `waiting_runs` IDs, and `waiting_runs_truncated`.
It also returns `event_cursor`, `finished`, and `more`. Without `since`, it
establishes a current cursor and returns no historical completions. With a
nonnegative event cursor, it reads up to 200 later run completion events.
Each completion contains its event `id`, `run_id`, `project_id`,
`workflow_key`, and `status`. Request text, event payloads, and provider
content are omitted. Use `event_cursor` as the next `since`, immediately when
`more` is true. This owner-only GET uses the existing integer bounds and
error envelopes; reading it never changes a request or run.

Run detail pages one collection at a time. `collection=nodes` is the default;
`collection=interactions` returns permission, elicitation, and wait records.
Both use the last numeric record ID as `since`. Stable run and snapshot
metadata accompanies every page. Node pages are monitor summaries; complete
provider and command output remains available through the event history.
Node summaries also include the latest attempt's `started_at` and `ended_at`
as UTC timestamps, or null before that attempt starts or finishes.

### Job history

`GET /api/runs/{id}/job?job=root.check` returns `job` and `next`. The job
contains its `scope_path`, `node_type`, `status`, `writes`, captured `command`
or human-wait `prompt`, `instructions`, current declared `outputs`, and a
bounded `attempts` page. `activity_type` identifies command, agent, and human
review steps within the Actions execution nodes. `display_name` retains the
resolved job or step name; historical views use their existing scope labels.
Agent instructions include the frozen prompt files and captured inline prompt.
Each instruction contains its local or global
`reference`, captured `text`, and `truncated` flag. The combined instruction
preview is limited to 256 KiB. It reads the launch snapshot, never current
prompt files.

Attempts contain `id`, `number`, `status`, `agent_id`, exact `model_value`,
`started_at`, `ended_at`, `stop_reason`, `exit_code`, `error_code`,
`error_message`, public `provider_message`, `provider_message_truncated`,
`starting_head`, and `ending_head`. Worker IDs, process IDs, live session
identifiers, and private provider content are omitted. `latest_attempt` is
returned separately even when it falls outside the requested attempt page.
Use `since=next` for further attempts; the existing numeric record bounds and
200-row page limit apply. Declared outputs describe the latest job result;
earlier attempt events and retained files remain available independently.

Event reads accept optional `job` and positive `attempt` filters before
pagination. Filtered job reads omit redacted events. For example,
`events?job=root.check&attempt=2&latest=true` returns
the last page of that exact attempt in ascending event order. In this mode,
`next` is an older-page cursor: send it as `before=next` with the same filters
and `latest=true`. Without `latest=true`, `since` and `next` keep their existing
forward behavior. Event payloads are unchanged.

`GET /api/runs/{id}/changes?job=root.check&attempt=2` previews that attempt's
committed changes, using its recorded starting and ending heads. It adds
`commits`, up to 100 records with `sha` and `title`, to the existing diff
response. No started attempt or no ending head yields no committed changes.
Omitting `attempt` selects the latest attempt; omitting `job` keeps the
existing whole-run response. Diff preview limits and disabled Git external
diff and text-conversion hooks still apply. Job reads require owner access;
unknown runs or jobs return the existing not-found error envelope.

### Live run detail

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
Each node also includes `repair_for`, either its source stage's scope or null.
A repair coordinator includes `repair_settings` with its captured round
budget, acceptance output and value, role configuration, and instructions.
Other nodes return null. Native policies set `legacy:false`; explicitly grouped
older loops set `legacy:true`. Node pages retain all repair coordinators and
child attempts so clients can inspect the full execution history.
Failed agent nodes also include `retry_settings`, containing their own
`scope_path`, effective `agent_id`, `model_value`, `effort`, `permission_mode`,
`default_handoff_prompt`, and `handoff_prompt_max_bytes`. Other nodes return
`null`. These settings let each failed step offer its own retry controls when
several agents fail, independently of the initiating problem notice.
Run detail includes `problem`, either `null` or the initiating failed attempt's
`scope_path`, `attempt_number`, `agent_id`, `model_value`, `error_code`,
`stop_reason`, `exit_code`, `message`, `provider_message`, and
`provider_message_truncated`. This metadata does not depend on the node or
event page cursor. It selects only the latest attempt of a currently failed
node, so a retried attempt's old error cannot become the current problem.
The provider text comes from that attempt's last normal, public `agent.message`,
never a thought, tool result, redacted event, or context-usage update. Up to
16 adjacent chunks with the same message ID and turn are joined in event order;
without an ID, only the last chunk is shown. For example, `"Limit · "` followed
by `"resets 1:50pm"` becomes `"Limit · resets 1:50pm"`. The notice is capped at
4,096 characters and flags omitted text. Full events remain in the event API.
`problem` is `null` for active retries, completed, canceled, and interrupted
runs; launch failures without an attempt retain `failure_summary` instead.
`problem.retry` is `null` or contains `state`, UTC ISO-8601 `reset_at`, and
`error_message`. States are `scheduled`, `blocked`, `canceled`, and `resumed`.
Only structured provider rejection metadata authorizes `scheduled`. A failed
run with a pending schedule keeps its SSE stream open so automatic recovery is
visible without reloading. Canceling or blocking the schedule lets a terminal
stream finish. Ordinary failed runs still end their stream.
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
| `agent.usage_limit` | `agent` | `reset_at` (UTC ISO-8601 or null), `window` (provider window or null), and `turn`; only a typed usage-limit failure authorizes recovery. |
| `run.retry_scheduled` | `run` | `scope_path`, confirmed `reset_at`, and `window` for the initiating failed step. |
| `run.retry_blocked` | `run` | `scope_path` and reset metadata, or a `message` explaining why workspace recovery stopped. |
| `run.retry_canceled` | `run` | The owner's cancellation `idempotency_key`; the run remains failed when already drained. |
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

`GET /api/runs/{id}/launch-inputs` returns `project_id`, a canonical
`workflow_key` (including its YAML suffix), `status`, and the previous typed
`inputs`. It is available only for failed, successful, or canceled runs;
active runs return `400 config_error`. The response excludes captured YAML,
prompts, and provider routes, and rejects inputs beyond the 1 MiB read limit.
The owner reviews these values in **Run workflow**, then posts to the existing
`/api/runs` launch endpoint. That request validates the current saved workflow,
Git source, inputs, artifacts, and fresh exact-model choices, and creates a new
snapshot. It does not reuse the previous snapshot or entry point.

Job detail also includes `retry_settings` for a failed agent job, with the same
public configuration fields as the existing run-detail node record. It is
`null` for other job types and states. Opening the settings dialog reads the
job again so another client's configuration change is reflected.

Run and job detail include `working_folder`, the recorded primary run folder.
The browser uses it to shorten paths in visible activity, including nested
`r-{attempt}` reader folders. This field does not read files or change paths;
original events and downloaded command output keep their recorded bytes.

Run cancel and rerun keys are stored in an indexed event column; duplicate
requests do not scan event payloads. Canceling a run still preparing its
worktree (`pending`) or awaiting restart reconciliation (`interrupted`) returns
`stale` (409). Retry with a new key after preparation or reconciliation finishes.
For a failed run with a scheduled usage retry, `cancel` returns `accepted` and
cancels that schedule without rewriting the failed attempt. A repeated request
returns `already_applied`. Manual `rerun-node` supersedes a pending schedule.

| Method and path | JSON body |
| --- | --- |
| `POST /api/runs/{id}/cancel` | `{"idempotency_key":"cancel-1"}` |
| `POST /api/attempts/{id}/permission` | `{"idempotency_key":"p-1","decision":"option-id"}` |
| `POST /api/attempts/{id}/elicitation` | `{"idempotency_key":"e-1","value":{...}}` |
| `POST /api/attempts/{id}/wait` | `{"idempotency_key":"w-1","value":...}` |
| `POST /api/runs/{id}/rerun-node` | `{"scope_path":"root.failed","idempotency_key":"r-1"}` |
| `POST /api/runs/{id}/pause` | `{"paused":true,"idempotency_key":"pause-1"}` |
| `POST /api/runs/{id}/step-settings` | `{"scope_path":"root.review","effort":"high","idempotency_key":"settings-1"}` |
| `POST /api/runs/{id}/recovery` | `{"enabled":true,"idempotency_key":"auto-1"}` |

The recovery action records a run-level policy override separately from the
immutable snapshot. `enabled` must be a JSON boolean. Enabling a failed run
queues its eligible initiating agent failure; disabling cancels pending error
recovery. It does not change a provider quota schedule or reset spent retries.
Completed and canceled runs return `stale`; duplicate keys return
`already_applied`. CSRF and owner controls match other run actions.

Run detail includes `recovery` with `enabled`, `max_retries`, and `current`.
`current` is null or the latest decision with `scope_path`, `attempt_number`,
`retry_number`, `state`, `instruction`, `instruction_sha256`, and `message`.
States are `scheduled`, `preparing`, `resumed`, `blocked`, `exhausted`, and
`canceled`. The instruction fits within 8,192 UTF-8 bytes. Original prompts and
snapshot hashes are unchanged.

SSE exposes `run.recovery_changed`, `run.recovery_scheduled`,
`run.recovery_preparing`, `run.recovery_resumed`, `run.recovery_blocked`,
`run.recovery_exhausted`, and `run.recovery_canceled`. Decision events include
the fields above; policy events include `enabled`, `max_retries`, and the
idempotency key. Recovery preparation errors include their scope and public
message. A failed run's stream stays open while error recovery is pending,
as it does for a pending quota reset. Run cancellation and manual retry
supersede queued error recovery through the existing recovery lock.

### Repair presentation

`POST /api/runs/{id}/repairs` records display groups for an existing captured
loop. The body contains `groups`, a mapping from concrete loop scopes to their
sibling source stages, and an `idempotency_key`. For example,
`{"groups":{"root.repairs":"root.review"},"idempotency_key":"display-1"}`
groups that loop and its scoped children under review. An empty mapping clears
legacy groups. Native policies already carry their own source association.

The run must have `dispatch_paused:true`; otherwise it returns `409 stale`.
Invalid associations return `422 invalid`. Each source has at most one grouped
loop. Replaying a successful key returns `already_applied`.
Success returns `accepted` and emits `run.repairs_changed`. The action saves
only presentation metadata. It does not rewrite snapshots, routes, prompts,
node statuses, attempts, or outputs. Owner and CSRF checks apply in both login
modes.

### Pause and unstarted-step settings

`pause` saves `dispatch_paused` without interrupting active attempts. The flag
appears in run summaries and detail and survives restart. `paused` must be a
JSON boolean. Pending, running, waiting, failed, and interrupted runs accept
the action; completed, canceled, and canceling runs return `stale`. Duplicate
keys return `already_applied`. Setting `paused:false` wakes queued tokens and
advances eligible steps. Error recovery and quota schedules wait while paused.
Deadlines continue to apply.

While paused, unstarted agent nodes expose `pending_settings` in run detail,
with the same configuration fields as `retry_settings` and a default handoff
for unstarted work. `step-settings` accepts `scope_path`, `idempotency_key`, and
the optional `agent_id`, `model`, `effort`, `permission_mode`, and
`handoff_prompt` choices described below. At least one setting is required.
Changing providers requires both `agent_id` and `model`. Null effort or mode
requests the provider default; omitted fields keep their current value unless
a replacement provider/model is supplied.

Only an agent in `pending`, `ready`, or `dispatched` with no prior attempt is
eligible. Relay validates against fresh provider configuration outside its
transaction, then rechecks the pause and target before saving. Ineligible
targets return `permission_flow_error` with HTTP `409`; races return
`{"result":"stale"}` with HTTP `409`. Unsupported choices keep their existing
HTTP `422` errors. A successful save returns `accepted` and keeps the run
paused. It creates no attempt and changes no snapshot, upstream work, other
nodes, or workspace. Duplicate keys return `already_applied`.

SSE exposes `run.dispatch_changed` with `paused` and `idempotency_key`, and
`node.settings_changed` with `scope_path`, `options`, and `idempotency_key`.
The latter records the effective per-node override separately from frozen
launch routes. Handoffs appear only for a changed tool/model pair and follow
the captured prompts on execution.

An agent rerun accepts an optional `effort` field. For example,
`{"scope_path":"root.review","idempotency_key":"r-2","effort":"medium"}`
requests Medium for that step's new attempts using its existing agent and exact
model. `"effort":null` requests the provider default. Omitting `effort` keeps
the current choice. Relay probes the selected model's configuration before
preparing the workspace; unsupported values return `agent_configuration_error`
with HTTP `422`, without reopening the step. Non-agent recovery targets reject
this field. A failed parent scope resolves to its deepest failed child, as with
an ordinary rerun.
The choice is saved outside the original snapshot, survives restart, and appears
in `run.rerun.payload.retry_options`. Later quota retries retain it. Repeating
the same idempotency key returns the first outcome and cannot change the choice.
The run's `problem.effort` and `problem.permission_mode` report its failed step's
current choices, with `null` for provider default. A permission-only change
uses `{"scope_path":"root.review","idempotency_key":"r-3","permission_mode":"ask"}`;
an explicit null restores the current tool's default. Omitted fields keep their
current values. Non-agent recovery targets reject these options.

To hand the failed agent step to another tool or model, supply both `agent_id`
and `model` on `rerun-node`. For example:

```json
{
  "scope_path": "root.refresh",
  "idempotency_key": "handoff-1",
  "agent_id": "antigravity",
  "model": "gemini-3.8-flash-high",
  "permission_mode": "auto_approve"
}
```

Relay freshly proves this exact selection and validates optional `effort` and
`permission_mode` values before workspace recovery. Supplying only one of the
two selection fields returns HTTP `400`.
Missing installations, unavailable models, and unsupported overrides retain
their Relay error envelopes and leave the failed step unchanged.

A replacement clears the previous tool's effort, mode, and permission profile;
omitted or null options use the new tool's defaults. Antigravity effort belongs
to the selected model slug. This affects only the resolved failed agent leaf's
future attempts. The original route table, prompts, earlier attempts, completed
steps, and other nodes' routes remain unchanged. The `run.rerun` event records
the complete replacement in `retry_options`, including `selected_agent`,
`model_value`, `effective_agent_order`, `effort`, `permission_mode`, and a null
`permission_profile`. Subsequent effort, permission, and quota retries keep it.
Repeating an accepted idempotency key cannot substitute a different selection.

A changed tool/model pair receives Relay's default continuation prompt after
its captured prompts. Supply `handoff_prompt` to replace that default with the
owner's exact text. The prompt must contain non-whitespace text and fit within
8,192 UTF-8 bytes. A custom handoff without a changed tool/model pair returns
HTTP `400`, leaving the failed step unchanged. The chosen text is retained in
`retry_options.handoff_prompt` and sent on later attempts, including quota
retries. Snapshot prompt bytes and hashes remain unchanged.
`problem.default_handoff_prompt` and `problem.handoff_prompt_max_bytes` expose
the default text and its limit for the retry dialog.

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

To select one run, include its UUID as `run_id`:

```json
{
  "scope": "worktrees",
  "run_id": "550e8400-e29b-41d4-a716-446655440000",
  "confirm": true
}
```

Omitting `run_id` retains project-wide cleanup. A supplied null, empty, or
non-string selector returns `400`; a malformed, unknown, or foreign-project
UUID returns `404`. None of these failures broadens the selection. The active
project-run check still applies. Selected cleanup shares the run's recovery
lock; an overlapping recovery returns `503` without removing the workspace.

Selected `worktrees` cleanup requires preserved artifact records and keeps
the run's history, artifacts, branch, and attempt refs. It records
`run.cleanup_succeeded` after removal. Selected `branches` or `runs` cleanup
retains the ordering requirements above. Selected `all` removes only that
run's resources and keeps process logs, which may contain other runs' output.

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
1 MiB, except library imports, which accept at most 10 MiB and 100 source files.
Control payloads are limited to 64 KiB. Reads and event frames are also
bounded so one browser request cannot load unbounded history. Unknown API paths
and unsupported methods also return JSON envelopes rather than the SPA or an
HTML error page.

Run path identifiers are UUIDs; attempt and artifact identifiers are positive
integers. A malformed or unknown identifier returns the same Relay-owned `404`
response and does not reach a state-changing service.

## Owner and project settings

These additive routes use the same owner access, loopback, host, and CSRF
protections as other APIs. Settings validation and inheritance are Python
services. They never mutate an existing run's snapshot or provider session.

| Method and path | Request | Success |
| --- | --- | --- |
| `GET /api/settings` | none | `200`; `settings`, exact-file `revision`, `active_login_required`, `username`, and storage `paths` |
| `POST /api/settings` | `settings` object and loaded `revision` | `200`; the same payload after an atomic save |
| `GET /api/projects/defaults` | optional `?project={id}` | `200`; explicit `overrides`, their `revision`, and resolved `effective` settings |
| `POST /api/projects/defaults` | `overrides` object and loaded `revision` | `200`; the same payload after a transactional save |
| `POST /api/projects/defaults` | `overrides` object and `preview: true` | `200 {"effective":...}`; validates and resolves without saving |
| `GET /api/data/usage` | optional `?project={id}` | `200`; project storage metadata and cleanup availability |

`settings` contains the existing `agent_preferences`, `cleanup_policy`, `host`,
`port`, `workers`, and `login_required`, plus `workflow_defaults`:

```json
{
  "model": null,
  "providers": {},
  "timeout": null,
  "auto_retry": true,
  "commands": {},
  "env": {},
  "recovery": {"enabled": false, "max_retries": 2},
  "repairs": {
    "max_rounds": 4,
    "fix_instruction": "Instructions for a newly added fixer role.",
    "verify_instruction": "Instructions for a newly added verifier role."
  }
}
```

Each `providers` key is a supported Relay agent ID. Its object accepts `model`,
`effort`, and `permission_mode`, preserving exact provider values. Thinking
and permission defaults require a model. Reads include resolved built-in
values; sparse settings files remain valid. A save replaces the submitted
settings object, so clients should send the complete loaded object.

`commands` maps lowercase node-ID-style names to nonempty string argument
lists. The first argument must be a nonempty program; no argument may contain
a NUL character. `env` maps nonempty variable names to string values. Names
cannot contain `=` or NUL; values cannot contain NUL. Both default to empty
maps. Existing settings, project defaults, and agent inventory endpoints expose
these additive fields through `workflow_defaults` or `defaults`.

Project overrides accept only `agent_preferences`, `cleanup_policy`, and
`workflow_defaults`. Omitted fields inherit; nested objects merge by field.
The `commands` and `env` maps each replace the entire inherited map when
present, including when empty. Other nested objects keep merging by field.
An explicit `null` model, timeout, effort, or permission removes that inherited
choice. Sending an empty overrides object restores all global defaults.
Changing a provider's model clears inherited effort and permissions unless
the project explicitly supplies replacements for that model.
Login and server options cannot be overridden per project.
A stale revision returns `409 settings_conflict`; validation errors retain
`400 config_error`. Filesystem and database failures use Relay envelopes and
retain private traces only in diagnostic logs. The active login policy stays
unchanged until restart, including when the saved setting differs.

`GET /api/agents` additively includes `defaults`, the selected project's
resolved `workflow_defaults`; `preferences` now reflects project overrides.
Workflow reads keep their existing `repair_defaults` shape, using saved
project/global values when the editor creates a new repair rule.
An omitted launch `cleanup_policy` uses the project's resolved setting.
Existing explicit launch fields and all control/event payloads are unchanged.
Workflow schema version 1 additionally accepts workflow `env` and `inherit_env`,
command-job `inherit_env`, and `run: {command: name}`. Launch resolves shared
commands and environment layers through Python services and freezes them in
node definitions and child snapshots. An unresolved name returns
`422 workflow_validation_error` without creating a run. Original YAML bytes
remain unchanged, and existing `run` arrays and old snapshots remain valid.

Storage usage returns `runs`, `artifacts`, `artifact_bytes`, `branches`,
`attempt_refs`, `cleanup_blocked`, and `working_copies` with `bytes`, `files`,
`directories`, and `truncated`. Working-copy measurement visits at most
50,000 entries and 1,000 run roots; incomplete counts are lower bounds.
It reads metadata only, follows no inner symlinks, and never returns file
contents. The existing confirmed `POST /api/data/clean` remains unchanged.

`GET /api/runs/<id>/artifacts/download` downloads retained attempt files as a
ZIP. The archive is limited to 1,000 files and 256 MiB and rejects changed
retained bytes. Artifact records include their attempt's completion or start
time as `created_at`. Run records expose `dispatch_paused_at` and accumulated
`dispatch_paused_seconds`; pause changes retain these counters transactionally.
