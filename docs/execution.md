# Relay execution

Relay runs each workflow from durable state in `relay.db`. Huey carries only an
opaque claim token. A queue item is never the record of whether work ran.

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
| `running` | `all_succeeded` | `all_nodes_terminal_success` | `succeeded` | `run.succeeded` |
| `running` | `node_failed` | `fail_fast` | `canceling` | `run.failing` |
| `paused_wait` | `node_failed` | `fail_fast` | `canceling` | `run.failing` |
| `running` | `owner_cancel` | `owner_requested` | `canceling` | `run.canceling` |
| `paused_wait` | `owner_cancel` | `owner_requested` | `canceling` | `run.canceling` |
| `canceling` | `cancel_drain_complete` | `owner_initiated_and_no_active_attempt` | `canceled` | `run.canceled` |
| `canceling` | `failure_drain_complete` | `failure_initiated_and_no_active_attempt` | `failed` | `run.failed` |
| `running` | `orderly_shutdown` | `shutdown_marker_set` | `interrupted` | `run.interrupted` |
| `paused_wait` | `orderly_shutdown` | `shutdown_marker_set` | `interrupted` | `run.interrupted` |
| `canceling` | `orderly_shutdown` | `shutdown_marker_set` | `interrupted` | `run.interrupted` |
| `interrupted` | `restart_reconcile` | `snapshot_and_artifacts_valid` | `running` | `run.resumed` |
| `failed` | `manual_rerun` | `owner_requested_failed_node` | `running` | `run.rerun` |
<!-- relay-transitions:run:end -->

### Nodes

<!-- relay-transitions:node:start -->
| From | Action | Guard | To | Event |
| --- | --- | --- | --- | --- |
| `(start)` | `create` | `always` | `pending` | `node.created` |
| `pending` | `dependencies_satisfied` | `needs_succeeded_and_guard_true` | `ready` | `node.ready` |
| `pending` | `guard_false` | `if_expression_false` | `skipped` | `node.skipped` |
| `pending` | `dependencies_unreachable` | `upstream_terminal_blocks_needs` | `skipped` | `node.skipped` |
| `ready` | `dispatch` | `claim_created` | `dispatched` | `node.dispatched` |
| `dispatched` | `attempt_started` | `claim_won_and_gate_acquired` | `running` | `node.running` |
| `running` | `interaction_requested` | `interaction_created` | `waiting` | `node.waiting` |
| `waiting` | `interaction_answered` | `control_applied` | `running` | `node.running` |
| `waiting` | `timeout_routed` | `on_timeout_declared` | `succeeded` | `node.succeeded` |
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
| `failed` | `rerun` | `owner_requested` | `ready` | `node.ready` |
| `canceled` | `recompute` | `canceled_only_by_fail_fast` | `pending` | `node.pending` |
<!-- relay-transitions:node:end -->

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
commits `ready` to `dispatched` with a new `DispatchClaim` in `relay.db`. It then
enqueues only the claim token in `huey.db` and records `enqueued_at`.

The consumer atomically claims a still-dispatched token, acquires admission, and
creates one `NodeAttempt` in the same Relay transaction. Duplicate tokens exit
without another attempt. A bounded reconciliation pass re-enqueues old,
unclaimed dispatches. It never re-enqueues a claim once an attempt began.
`run_node_attempt` is declared with `retries=0`; Relay does not retry a failed,
lost, timed-out, canceled, or soft-denied attempt.

## Controls and waits

Permission answers, elicitation answers, wait answers, and cancels are durable
`ControlRequest` rows tied to one attempt. The live worker may claim only its own
attempt's request. It applies the request before recording the corresponding
answer event. An expired request or one for an older attempt becomes `stale`.
Posting the same idempotency key again does not apply the answer twice.

A claimed control has a heartbeat lease. Reconciliation returns it to `pending`
only while the same attempt remains live. If its owner is gone, the request is
stale and the attempt follows interruption or worker-loss handling. Pending
interactions are discarded when their attempt is lost.

Human-wait nodes have no subprocess. Their attempt stays durable while the run
is paused. A deadline takes the declared `on_timeout` edge; without that edge,
the node fails with `timeout`.

## Node execution

| Type | Runtime behavior |
| --- | --- |
| `agent` | Starts one fresh routed agent session, sends the snapshotted prompts and declared context, and validates outputs after the session ends. |
| `command` | Runs the declared argument vector with `shell=False`, merges `env` over the inherited environment, and records complete stdout, stderr, exit status, and elapsed time in bounded event chunks. |
| `human_wait` | Creates a durable owner question with no subprocess. The current attempt completes after an answer, deadline, cancellation, or recovery decision. |
| `condition` | Evaluates one restricted expression and records the target for the matching branch label. Unselected branch targets become `skipped`. |
| `loop` | Executes its child graph in numbered scopes until `until` is true or `max_iterations` selects the `exhausted` target. |
| `subworkflow` | Executes a captured child workflow in the same run, with only its declared inputs and outputs crossing the scope boundary. |

Every declared `timeout` becomes one monotonic attempt deadline. A loop or
subworkflow passes its remaining deadline into each nested attempt, so child
work cannot outlive the enclosing node. A running timeout fails with stop
reason `timeout`; a waiting `human_wait` may instead select its declared
`on_timeout` edge.

Agent and command nodes extract every declared output before success. Files
used by `label`, `json_path`, and `yaml_path` selectors are required artifacts;
Relay copies them to central evidence storage with their SHA-256 hashes. An
`exists` selector returns a boolean and does not make a missing file an error.

Loop and subworkflow child graphs execute inline in the enclosing consumer
thread. This avoids an enqueue-and-wait deadlock when `relay up` uses its
default single worker. Each child heartbeat also renews its bounded chain of
enclosing attempts, so a long child cannot make its owning loop or subworkflow
look abandoned. A nested human wait still owns no subprocess: the enclosing
scope checks the durable mailbox at the fixed control cadence until the answer
or deadline settles the child node.

## Nested scope example

Suppose loop `build_loop` reaches iteration 2. Its body invokes subworkflow
`verify`, whose child node `check` produces output `ready`. Relay records these
rows:

| `scope_path` | `parent_scope_path` | Meaning |
| --- | --- | --- |
| `root.build_loop#2` | `root` | Structural record for loop iteration 2. |
| `root.build_loop#2.verify` | `root.build_loop#2` | The subworkflow invocation in that iteration. |
| `root.build_loop#2.verify.check` | `root.build_loop#2.verify` | The child node executed by `verify`. |

Inside the subworkflow, `check` reads its siblings within
`root.build_loop#2.verify`. The subworkflow maps `check.ready` to its own
`ready` output. The loop then reads that value as
`needs.verify.outputs.ready`, scoped to `root.build_loop#2`; it cannot read an
output from iteration 1 or 3.

## Failure, cancellation, and recovery

The first node failure moves the run to `canceling`, prevents pending work from
starting, and sends one durable cancel request to each active sibling attempt.
Agent cancellation asks the protocol session to stop, then Relay terminates the
whole process tree after the fixed grace period. Command cancellation uses the
same bounded process-tree stop. Evidence preservation precedes worktree removal
and lock release.

An owner may rerun one failed node after Relay preserves its evidence and resets
only that attempt's changes. For a nested failure, Relay reopens the failed leaf
and its loop or subworkflow parents so the synchronous scope can reach that
leaf. Successful nodes remain complete. Nodes canceled only by fail-fast return
to `pending` and have eligibility recomputed. If a separate concurrent failure
remains, the run returns to `failed` after the selected rerun settles. This is a
new attempt initiated by the owner, not an automatic retry.

During orderly shutdown, active attempts end as `interrupted` and their nodes
return to `pending`. Restart reconciliation validates retained inputs and
artifacts, then creates new attempts. An unmarked stale heartbeat ends as
`worker_lost` and triggers fail-fast instead.

## Scheduling and worktree admission

Each durable scheduling pass loads and compiles the graph once, then drains a
bounded queue of direct data and control successors. A pass is O(V+E); within
that pass, a terminal update enqueues only O(outdegree) candidates. Loop and
subworkflow expansion is bounded before execution.

Nodes that do not touch Git state need no worktree gate. Git-backed read-only
nodes may run together, each in a detached ephemeral worktree at the run's
recorded commit. A writer acquires the exclusive run lock and uses the primary
worktree. A reader worktree is removed before its node advances. A writer lock
is released only after commit validation, evidence preservation, and the new
recorded HEAD are durable.

One Huey consumer process uses thread workers on Linux, Windows, and macOS. The
default is one worker; a configured count permits read-only parallelism while
the durable admission lock still excludes writers. SQLite transactions are
short, use WAL, and fail after the configured busy timeout rather than retrying
without a bound.
