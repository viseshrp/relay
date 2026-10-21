# Relay execution

Current workflows use the [Actions jobs/steps dialect](workflows.md). One
durable installation-wide lease admits a job and its nested/matrix steps
serially. Each step is a committed attempt. Jobs suspend for owner/environment
gates without repeating completed steps. Deadlines and matrix manifests
persist through restart. Job success validates the cumulative Git checkpoint;
agents can defer commits until that boundary.

Raw outcomes and effective conclusions are stored separately. Failed steps
admit explicit failure follow-ups; failed jobs do not cancel unrelated jobs.
`continue-on-error` affects conclusions while retaining rejected evidence.
Step conditions reconcile with recorded results, including failures before
the executor starts. A timed-out step still honors `continue-on-error`.
Only compiled jobs and steps execute.

Relay runs each workflow from durable state in `relay.db`. Huey carries only an
opaque claim token. A queue item is never the record of whether work ran.

Launch resolves omitted workflow choices from project and global settings, then
captures the resulting definitions, routes, and recovery policy in the snapshot.
Settings changes affect future launches. Retries and later child jobs continue
to use the captured choices; original YAML and prompts retain their exact bytes.
See [Installation defaults](workflows.md#installation-defaults).

## State transitions

`relay/execution/state.py` is the source for these tables. Each accepted
transition and its event are committed together. Reapplying an action after its
target state already holds is a no-op.

### Runs

<!-- relay-transitions:run:start -->
| From | Action | Guard | To | Event |
| --- | --- | --- | --- | --- |
| `(start)` | `launch` | `preflight_passed` | `pending` | `run.created` |
| `pending` | `worktree_ready` | `branch_and_worktree_created` | `running` | `run.started` |
| `pending` | `worktree_failed` | `creation_error` | `failed` | `run.failed` |
| `running` | `node_waiting` | `one_or_more_nodes_waiting` | `paused_wait` | `run.paused` |
| `paused_wait` | `wait_answered` | `no_waiting_nodes_and_none_failed` | `running` | `run.resumed` |
| `paused_wait` | `jobs_settled` | `actions_jobs_and_descendants_terminal` | `running` | `run.resumed` |
| `running` | `all_succeeded` | `all_nodes_terminal_success` | `succeeded` | `run.succeeded` |
| `running` | `jobs_canceled` | `all_jobs_terminal_with_cancellation_and_none_failed` | `canceled` | `run.canceled` |
| `running` | `completion_started` | `all_nodes_terminal_success_and_merge_requested` | `completing` | `run.completing` |
| `completing` | `completion_succeeded` | `merge_and_worktree_removal_durable` | `succeeded` | `run.succeeded` |
| `completing` | `completion_failed` | `merge_or_worktree_removal_failed` | `failed` | `run.failed` |
| `running` | `node_failed` | `fail_fast` | `canceling` | `run.failing` |
| `paused_wait` | `node_failed` | `fail_fast` | `canceling` | `run.failing` |
| `running` | `owner_cancel` | `owner_requested` | `canceling` | `run.canceling` |
| `paused_wait` | `owner_cancel` | `owner_requested` | `canceling` | `run.canceling` |
| `canceling` | `cancel_drain_complete` | `owner_initiated_and_no_active_attempt` | `canceled` | `run.canceled` |
| `canceling` | `failure_drain_complete` | `failure_initiated_and_no_active_attempt` | `failed` | `run.failed` |
| `running` | `orderly_shutdown` | `shutdown_marker_set` | `interrupted` | `run.interrupted` |
| `paused_wait` | `orderly_shutdown` | `shutdown_marker_set` | `interrupted` | `run.interrupted` |
| `interrupted` | `restart_reconcile` | `snapshot_and_artifacts_valid` | `running` | `run.resumed` |
| `failed` | `manual_rerun` | `owner_or_confirmed_reset_or_configured_recovery` | `running` | `run.rerun` |
<!-- relay-transitions:run:end -->

A run succeeds only when every node is `succeeded` or `skipped`. A terminal
`canceled` node cannot satisfy the `all_succeeded` guard.
With `cleanup_policy: "merge_on_success"`, all successful jobs instead enter
`completing`. The run succeeds only after the captured launch branch has been
fast-forwarded and its working copy removed. Integration failures fail the run
without changing completed job results. The merge commit is durable before
cleanup; reconciliation resumes this state after a restart without reopening
jobs. See [Run integration](git-and-artifacts.md#opt-in-run-integration).
Canceling runs keep their owner-cancel or fail-fast intent during shutdown.
Successful attempts keep their outputs and protected commits, and failed
attempts keep their failure details. An interrupted attempt in a canceling run
settles as canceled instead of reopening its node. The run drains to `canceled`
or `failed`; restart never reopens canceled nodes.

After an owner answers a wait, resuming its enclosing job or nested scope
also updates the run status. Once no waiting or failed nodes remain, the run
returns to `running` before its next step finishes. A second pending wait
keeps the run in `paused_wait`.

### Nodes

<!-- relay-transitions:node:start -->
| From | Action | Guard | To | Event |
| --- | --- | --- | --- | --- |
| `(start)` | `create` | `always` | `pending` | `node.created` |
| `pending` | `dependencies_satisfied` | `needs_succeeded_and_guard_true` | `ready` | `node.ready` |
| `pending` | `guard_false` | `if_expression_false` | `skipped` | `node.skipped` |
| `pending` | `dependencies_unreachable` | `upstream_terminal_blocks_needs` | `skipped` | `node.skipped` |
| `ready` | `dispatch` | `claim_created` | `dispatched` | `node.dispatched` |
| `dispatched` | `admission_failed` | `invalid_frozen_admission_policy` | `failed` | `node.failed` |
| `dispatched` | `attempt_started` | `claim_won_and_gate_acquired` | `running` | `node.running` |
| `running` | `interaction_requested` | `interaction_created` | `waiting` | `node.waiting` |
| `waiting` | `interaction_answered` | `control_applied` | `running` | `node.running` |
| `running` | `scope_waiting` | `child_wait_or_admission_deferred` | `waiting` | `node.waiting` |
| `waiting` | `scope_ready` | `child_settled_or_admission_available` | `dispatched` | `node.dispatched` |
| `running` | `complete` | `outputs_and_commit_valid` | `succeeded` | `node.succeeded` |
| `running` | `fail` | `attempt_failed` | `failed` | `node.failed` |
| `waiting` | `fail` | `timeout_or_worker_lost` | `failed` | `node.failed` |
| `running` | `cancel` | `run_canceling` | `canceled` | `node.canceled` |
| `waiting` | `cancel` | `run_canceling` | `canceled` | `node.canceled` |
| `pending` | `fail_fast` | `run_canceling` | `canceled` | `node.canceled` |
| `ready` | `fail_fast` | `run_canceling` | `canceled` | `node.canceled` |
| `dispatched` | `fail_fast` | `run_canceling` | `canceled` | `node.canceled` |
| `running` | `interrupt` | `orderly_shutdown` | `pending` | `node.interrupted` |
| `waiting` | `interrupt` | `orderly_shutdown` | `pending` | `node.interrupted` |
| `failed` | `rerun` | `owner_or_authorized_recovery` | `ready` | `node.ready` |
| `canceled` | `recompute` | `canceled_only_by_fail_fast` | `pending` | `node.pending` |
<!-- relay-transitions:node:end -->

Every job, step, reusable-workflow invocation, and loop iteration uses the
same durable attempt and dispatch rules. Current loop scopes use ordinary
segments such as `root.build.repeat.iteration_2.check`; no structural `#2`
records or separate iteration-summary state machine exist. Retrying a failed
leaf reopens its enclosing current coordinators while completed steps retain
their results.

### Human interactions

<!-- relay-transitions:interaction:start -->
| From | Action | Guard | To | Event |
| --- | --- | --- | --- | --- |
| `(start)` | `request` | `current_attempt` | `pending` | `requested` |
| `pending` | `answer` | `matching_control_applied` | `answered` | `answered` |
| `pending` | `deadline` | `deadline_reached` | `expired` | `expired` |
| `pending` | `attempt_lost` | `cancel_shutdown_or_loss` | `discarded` | `discarded` |
<!-- relay-transitions:interaction:end -->

### Control requests

<!-- relay-transitions:control:start -->
| From | Action | Guard | To | Event |
| --- | --- | --- | --- | --- |
| `(start)` | `post` | `authenticated_and_valid` | `pending` | `accepted` |
| `pending` | `claim` | `current_attempt` | `claimed` | `claimed` |
| `claimed` | `apply` | `live_session` | `applied` | `applied` |
| `claimed` | `lease_recover` | `attempt_session_still_live` | `pending` | `pending` |
| `pending` | `supersede` | `not_current_attempt` | `stale` | `stale` |
| `claimed` | `supersede` | `not_current_attempt_or_expired` | `stale` | `stale` |
| `(start)` | `reject` | `invalid_payload` | `invalid` | `invalid` |
<!-- relay-transitions:control:end -->

## Dispatch durability

Dispatch has two database files and no cross-database transaction. Relay first
commits `ready` to `dispatched` with a new `DispatchClaim` in `relay.db`. It
then enqueues only the claim token in `huey.db` and records `enqueued_at`.

Launch, resume, and rerun HTTP handlers commit their state and events without
scheduling. The worker follows those events and schedules eligible nodes. At
startup it also delivers existing dispatched claims, including suspended scopes
that reuse an attempt. Committed delivery events repair a missing web-process
notifier; duplicate Huey delivery still cannot create a second attempt.

The consumer atomically claims a still-dispatched token, acquires admission, and
creates one `NodeAttempt` in the same Relay transaction. Duplicate tokens exit
without another attempt. A bounded reconciliation pass re-enqueues old,
unclaimed dispatches. It never re-enqueues a claim once an attempt began.
Concurrent scheduling passes recheck the node inside the Relay transaction. If
another caller already started, finished, or canceled it, the stale dispatch
does nothing. Duplicate deliveries of an existing claim still create one
attempt. `run_node_attempt` is declared with `retries=0`. Queue delivery never
retries an attempt. A confirmed provider usage reset can authorize a fresh
failed-node recovery as described below. An explicitly enabled recovery policy
also authorizes bounded retries for eligible agent failures.

### Bounded workflow loops

Fix-and-check work is an explicit `relay/loop@v1` step calling a captured local
reusable workflow. Each iteration retains its attempts and outputs. The loop
stops when its declared condition passes or fails with `loop_exhausted` when
its iteration limit is spent. Its source defines the agents, commands, and
acceptance outputs for each iteration. See
[Stage repair rules](workflows.md#stage-repair-rules).

### Automatic step recovery

Automatic recovery is disabled by default. The workflow's `recovery` policy sets
a budget of one or two additional attempts per agent step. The owner can enable
or disable it on an existing run through the browser or recovery API, without
modifying the captured workflow. The agent action input `auto-retry: false` opts
a step out.

Eligible error codes are `output_validation_error`, `commit_validation_error`,
`dirty_repository_error`, and `node_timeout`.
An agent step that changes paths outside its
[`allowed-paths`](workflows.md#allowed-paths) fails with
`output_validation_error`, so repair receives the offending paths.
Provider execution and protocol failures require an owner decision and create no
automatic repair instruction or schedule. Cancellation, interruption,
permission refusal, unavailable models, unsafe
paths, storage failures, preservation failures, and Git recovery failures never
launch an automatic attempt. A failed command does not receive an automatic
agent retry. Explicit step conditions and loops retain their declared failure
handling.

`AutomaticRetry` records one decision for the initiating failed attempt.
Within a live job, the executor retries the failed agent step in the same
workspace while retaining completed steps. After a terminal job failure,
reconciliation waits for admission to be released, verifies the protected
workspace and retained evidence, and reopens the failed leaf and its current
coordinators. Independent failed steps block recovery.

Owner retries verify the evidence manifest, every retained file hash, and its
Git reference. The primary workspace must still match its protected head with
only the exact root-report exemptions. Relay preserves missing required
evidence before verification; human-wait steps carry no evidence. Damaged
evidence, dirty code, staged reports, or a changed head block recovery. Failed
jobs retain their private continuation state for a safe retry; confirmed cleanup
can remove it when the run is no longer needed.

Relay appends the error and the following instruction as a separate prompt:

> Recover only this failed step. Follow its original instructions and scope.
> Read the retained evidence and existing reports before acting. Fix the
> supplied error and preserve completed work. Do not start new feature work,
> change models or permissions, weaken checks, invent evidence, or turn failing
> verdicts into passes. Report genuine blockers when the original scope cannot
> resolve them.

The text and its SHA-256 hash are recorded in the recovery decision and event.
Original prompt bytes, snapshot hashes, routes, and settings stay unchanged.
Run metadata points the agent to the retained attempt evidence. When the
failed attempt retained an evidence index, the instruction also contains an
`Evidence index: <path>` line before the failure text, so the agent can read
the full failure and the retained diff, untracked files, and rejected report
instead of searching for them. A path longer than a quarter of the 8 KiB
instruction limit is omitted rather than cut. Model-switch handoff
instructions remain a separate owner-selected control.

The per-run kernel recovery lock serializes automatic, quota, and manual
retries. The decision is rechecked after workspace preparation. Duplicate
delivery, restarts, and repeated failures do not replenish the budget. A crash
during preparation resumes that same decision; a third eligible failure after
two retries records `exhausted` and stops. Owner cancellation or disabling the
policy removes pending recovery. A manual retry supersedes it. Orderly
shutdown suspends preparation and activation until restart.

Provider quota schedules take precedence and keep their existing requirement
for a structured, confirmed reset. A quota retry keeps any existing recovery
instruction and does not spend an additional error-recovery retry.

### Provider usage resets

Claude's typed ACP `errorKind: rate_limit` identifies a usage-limit failure.
Only a rejected `_claude/rateLimit` update with a valid future `resetsAt`
authorizes automatic recovery. Warning windows, context-token counts, private
thoughts, and reset times in prose never authorize it. An unknown or expired
reset leaves the run visibly blocked for manual recovery.

Relay stores the initiating attempt and UTC reset in `UsageRetry`. A current
job yields while waiting for a confirmed future reset and keeps the run
`running` unless a separate owner gate pauses it. Due reconciliation wakes
that job once; the same job attempt continues with a new failed-step attempt.
Completed steps and the accepted Git checkpoint remain intact. The schedule
survives restart and does not require an open browser.

Terminal failures use the same recovery lock and workspace checks as owner
retries. Another independent failure or invalid evidence blocks recovery with
its recorded reason. Unknown and expired resets are recorded as `blocked`
and never authorize an automatic attempt.

Recovery uses the frozen prompts, route, model, permissions, and current effort
choice. Explicit owner retry settings may replace that step's route as
explained below. Another usage failure needs another confirmed future reset.
Canceling the run removes the schedule; owner retry supersedes it. Pausing new
steps holds due work until the owner resumes. Shutdown retains the schedule.

## Controls and waits

Permission answers, elicitation answers, wait answers, and cancels are durable
`ControlRequest` rows tied to one attempt. The live worker may claim only its
own attempt's request. It applies the request before recording the corresponding
answer event. An expired request or one for an older attempt becomes `stale`.
Posting the same idempotency key again does not apply the answer twice.

Empty control polls check with a read before reserving SQLite's writer. The
claim transaction rechecks ownership, expiry, and request state. Periodic
reconciliation runs once per second and checks for due work before writing.
An installation with no active or due work writes only its supervisor lease;
unchanged trigger observations do not write new cursor values.

A claimed control has a heartbeat lease. Reconciliation rechecks its state,
expiry, lease age, and owner after acquiring the write lock. It returns the
control to `pending` only while the same attempt remains live. If its owner is
gone, the request is stale and the attempt follows interruption or worker-loss
handling. Pending interactions are discarded when their attempt is lost.

The `relay/human-wait@v1` step has no subprocess. Its question and attempt
remain durable while the job yields. A deadline fails the step with `timeout`;
there is no alternate timeout edge. Step conditions and `continue-on-error`
control the following work.

One coordinator in the worker process renews all registered attempts and their
admission locks once every five seconds, in one short transaction. Nested
scopes share registrations; each attempt renews once per cycle. Registrations
cover execution, command-output retention, Git validation, evidence
preservation, and job checkpoint finalization. Provider and command loops check
ownership through reads.

Heartbeat renewal retries transient SQLite busy errors within a 30-second
total budget. Exhaustion stops the worker so the supervisor can prove it has
exited before recovery. This is an unexpected child exit: Relay stops rather
than automatically restarting the worker. Attempt heartbeats support control
claim recovery; their age never authorizes workspace handoff. Launch
persistence and control transactions retry only rolled-back SQLite busy
failures within a 15-second total budget, including SQLite's own waiting.
Git operations, provider calls, and agent execution are never repeated by a
database retry. Other database errors propagate unchanged.

## Node execution

Only two node types are persisted and dispatched:

| Type | Runtime behavior |
| --- | --- |
| `actions_job` | Coordinates ordered steps, reusable calls, or matrix variants; owns the shared workspace and accepts one cumulative Git checkpoint after success. |
| `actions_step` | Executes a script, local action, or builtin such as `relay/agent@v1`, `relay/command@v1`, `relay/human-wait@v1`, or `relay/loop@v1`. |

Agent steps start a fresh routed session using captured prompts and validated
provider settings. Command steps execute the captured argument vector with
`shell=False`; script steps use the selected interpreter through that same
process adapter. Human waits create durable owner questions. Loops invoke a
captured reusable workflow within their configured bound.

Captured `timeout-minutes` and inherited timeout defaults produce durable
attempt deadlines. Nested work cannot outlive its enclosing deadline.
Reconciliation enforces suspended deadlines without holding the worker.

Command output is retained while the process runs, using separate readers
for stdout and stderr so reading cannot change the child's write offsets.
Each control poll drains a bounded number of chunks before checking timeout,
cancellation, and worker ownership. An incremental UTF-8 decoder preserves
characters split across reads. Process exit drains the remaining bytes,
including output from canceled or timed-out commands. Child programs must
flush their own buffers for immediate output.

On Windows, the owned launcher resolves the target against the attempt's
inherited `PATH` and working directory before starting its absolute path.
This preserves workflow-selected tools instead of allowing the launcher's
application directory to take priority. Arguments stay separate, and the
target starts only after the launcher joins its kill-on-close Job Object.

Agent and validation actions extract every declared report output before
success. Files used by `label`, `json_path`, and `yaml_path` selectors are
required artifacts; Relay copies them to central evidence storage with their
SHA-256 hashes. An `exists` selector returns a boolean and does not make a
missing file an error.

Reusable jobs and loop iterations execute through the same consumer thread.
The shared coordinator renews child and enclosing attempts together. When a
child waits for the owner, quota, or job admission, its parent yields. A child
settlement redispatches the same parent attempt, which reads its saved state
and continues without repeating successful children. Only the declared human
wait creates an owner question.

## Nested scope example

Suppose job `build` has loop step `repeat`, which invokes a reusable workflow
whose `verify` job contains step `check`. In iteration 2 the records are:

| `scope_path` | `parent_scope_path` | Meaning |
| --- | --- | --- |
| `root.build` | `root` | The owning job. |
| `root.build.repeat` | `root.build` | The bounded loop step. |
| `root.build.repeat.iteration_2` | `root.build.repeat` | The captured reusable invocation for iteration 2. |
| `root.build.repeat.iteration_2.verify` | `root.build.repeat.iteration_2` | Its verification job. |
| `root.build.repeat.iteration_2.verify.check` | `root.build.repeat.iteration_2.verify` | Its check step. |

Each record has its own attempt. The reusable workflow maps its declared
outputs back to the loop. Scope membership compares complete dot-separated
segments, so iteration 2 cannot read a sibling iteration's private results.

## Failure, cancellation, and recovery

When an executor raises a Relay error, its public description is saved in
`failure_summary` and the `attempt.ended` event's `error_message`. The event
also includes `error_code`; existing codes and terminal outcomes retain their
meaning. Descriptions keep at most their first 4,096 characters. For example, a
5,000-character description retains its 4,096-character prefix. Unexpected
exceptions expose a generic Relay description while their trace stays in the
application log. The run monitor combines this diagnostic with the failed
attempt's exit code and last public provider message. A rerun clears the run
summary and shows only the new attempt's failure if it fails again.

A failed step settles its raw outcome and effective conclusion. The owning
job evaluates later step conditions and `continue-on-error`; other jobs retain
their own dependency and failure rules. Owner cancellation prevents new work,
sends durable requests to live attempts, and redispatches yielded scopes so
their cleanup can finish. Agent and command processes use bounded owned-tree
shutdown. Evidence preservation precedes workspace removal and admission
release.

Before an unrelated job continues, Relay preserves missing evidence from the
failed job's primary workspace and verifies it before moving that checkout
aside. Each failed job and step attempt requires complete evidence; a
preservation failure blocks continuation. Human-wait steps keep their evidence
exemption. See
[Actions job boundaries](git-and-artifacts.md#actions-job-boundaries).

An owner may retry a failed current step or job after evidence and protected
workspace checks. Job and step attempts require retained evidence, except
human-wait steps. Relay preserves missing attempt evidence from the current
workspace before a retry or confirmed cleanup, then verifies it; damaged
evidence still blocks either operation. Relay reopens the failed leaf and its
current enclosing coordinators, retaining completed steps, their outputs, and
accepted commits.
Fail-fast-only canceled work has eligibility recomputed. An independent
remaining failure still prevents the run from succeeding. The retry creates a
fresh attempt using the retained job state.

An owner retry may explicitly change an agent step's effort to a value freshly
advertised for its existing model, change its permission mode, or request the
provider defaults. It may also select another installed agent and exact model
for that failed step. Relay
proves the new selection and validates its effort and permission mode before
preparing the workspace. A replacement starts with that tool's defaults unless
the owner selects supported overrides; options from the previous tool do not
carry over. Antigravity effort remains encoded in its exact model slug.

Relay stores the choice on that node and in the `run.rerun` event, separately
from the immutable launch snapshot. Only that step's new attempts use the
replacement. Completed nodes, previous attempts, prompts, other nodes' routes,
and snapshot hashes keep their captured values. The choice survives restart and
later automatic quota recovery. A subsequent effort or permission change
preserves the replacement agent and model. Omitting all choices keeps the
current route.
Relay never changes providers automatically in response to an error.

### Pause new steps and change an unstarted agent

An owner can pause new steps while a provider session is running. The saved
`dispatch_paused` flag blocks admission, including tokens already in Huey's
queue. Existing attempts keep their sessions and can finish, retain outputs,
and finish normally. Changed code advances the protected head only at a
successful job boundary. This flag survives restart and does
not change the run's state-machine status or freeze its deadlines. Nested scopes
yield while their children wait, releasing worker capacity.

Automatic error recovery and confirmed quota schedules wait while this flag is
set; pausing does not cancel a schedule or reset its spent retry budget. Resume
new steps explicitly to wake existing dispatch intent and advance successors.

While paused, a materialized agent step in `pending`, `ready`, or `dispatched`
can receive new settings only if it has never started an attempt. Relay freshly
proves the chosen tool/model and validates supported effort and permission
choices before atomically rechecking the pause, admission, and previous
settings. A concurrent resume, attempt start, or settings edit rejects a stale
save. Saving settings keeps the run paused and does not reset its worktree or
create an attempt.

The selection uses the same durable per-node override as retry settings.
Completed work, frozen prompts, snapshot hashes, and other nodes' settings stay
unchanged. A changed tool/model appends an editable default handoff describing
an unstarted step; effort or permission changes alone add no handoff. The
selected provider starts a new session when the owner resumes new steps.

Changing the tool/model pair appends a default continuation prompt to that
step's captured prompt sequence. The owner can replace it with custom handoff
instructions. Those instructions remain separate from the snapshot and survive
subsequent retries. An effort-only or permission-only change adds no new
handoff. The browser shows the handoff editor only for a changed tool/model
pair, with an option to restore the default text.

During orderly shutdown, interrupted attempts in canceling runs end as
`canceled`. Successful and failed results keep their original outcome while
the run drains to the owner's canceled result or fail-fast failure.
Other active attempts end as `interrupted` and their nodes
return to `pending`. Restart reconciliation validates retained inputs and
artifacts, then creates new attempts. Unexpected worker exit ends its active
attempts as `worker_lost` and triggers fail-fast after process exit is proved.
An old heartbeat alone never releases a live worker's admission or workspace.
Sleep and wall-clock changes do not authorize a replacement writer.

The supervisor stops its web and worker children even if it loses its lease
or cannot persist shutdown intent. A marker written before a persistence
failure stays available for restart reconciliation. The supervisor releases
its own lease after child cleanup and reports a shutdown failure.
If a child refuses to exit, attempts and their admission remain held and the
ownership record stays available for the next startup. No worker restarts
automatically.

### Restart after a lost supervisor

`relay up` holds a kernel lock for its whole lifetime. A second supervisor
cannot take over while that lock is held. The operating system releases it
when the supervisor exits, including after an abrupt termination.

The supervisor atomically records its instance UUID, host, and the PID and
creation time of itself and its web and worker children. On the next start,
Relay checks that the recorded supervisor has exited before releasing that
exact database lease. A live matching supervisor remains authoritative even
if its database heartbeat is stale.

Relay gates new work, records shutdown intent, and stops only children whose
current creation time matches the record. It rechecks that identity before
force-stop. A reused PID is left alone. Linux identities combine the boot ID
and process start ticks; Windows uses `GetProcessTimes`; macOS uses
`PROC_PIDTBSDINFO`. Active command and agent attempts also retain their creation
time. Recovery waits for verified attempts to exit before reconciling their
worktrees.
The supervisor checks surviving POSIX group members and Windows job
descendants as well as the recorded process. If an exited POSIX leader left
children whose creation identities were never observed, recovery stops and
retains the workspace. A saved group number alone cannot authorize a kill.

After cleanup, Relay reclaims the requested port, reconciles interrupted work,
and starts fresh children. Completed runs, successful nodes, recorded commits,
and frozen snapshots remain intact. Cancel and fail-fast intent follow the
shutdown rules above. The ownership record is removed only after its matching
children exit.

Unrelated port occupants, missing or invalid ownership records, links, another
host's record, and unverifiable process identities never authorize a stop.
A live attempt without a creation token blocks workspace recovery;
stop that worker normally first. Relay reports the reason and preserves
its worktree instead of guessing ownership.

## Scheduling and worktree admission

Unstarted stale dispatches are repaired for both `running` and `paused_wait`
runs. An unrelated human wait does not prevent a writer's delivery repair.
A settled owner wait resumes the run only when no waiting or failed node
remains, using the same guard for answers and deadline failures.
If completing the wait wakes an enclosing scope, expiry reads the current run
status so that the same resume transition is recorded only once.

Consumer startup initializes each active run once in O(V+E). Compiled immutable
graphs are cached in a bounded cache. Later committed node changes schedule
only their run and direct dependency successors, loading candidate rows and
their dependencies instead of walking every active graph. A terminal change
starts with O(outdegree) candidates; skipped successors propagate through their
own edges. Matrix, reusable-workflow, and loop expansion remain bounded.
Eligibility changes apply only while the locked node is still `pending`. A
concurrent pass uses the current status instead of applying an old decision;
if the node already succeeded, it loads the committed outputs before considering
successors. These checks do not add transitions to the tables above.

One durable installation-wide job lease admits current jobs serially. All
steps in that job share the primary run workspace. A successful job commits its
changed code once; a clean no-op is valid. The lease remains held until Git
validation, preservation, and the protected head are durable.

Released admission wakes deferred delivery through the consumer. Bounded
stale-dispatch reconciliation repairs enqueue loss or consumer restart.
Nested waits yield the worker and retain their captured deadlines.

One Huey consumer process uses exactly one execution thread on Linux, Windows,
and macOS. Execution concurrency is fixed and has no configuration field.
The reconciler and heartbeat coordinator remain separate background threads.
SQLite transactions stay short, use WAL with FULL durability, and have bounded
busy waiting.
