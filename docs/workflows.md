# Workflows

Relay reads versioned YAML files from `.relay/workflows/`. A workflow is a map
of named nodes. Relay rejects unknown keys, unsupported schema versions,
invalid references, recursive subworkflows, and dependency cycles before a run
is created.

`relay init` supplies only an empty version 1 workflow. The examples below
explain the format; Relay does not install them as templates.

## Top-level fields

| Field | Required | Value |
| --- | --- | --- |
| `version` | yes | Integer `1`. Other versions fail without rewriting the file. |
| `name` | yes | Non-empty display name. |
| `inputs` | no | Map of typed launch inputs. |
| `model` | no | Exact, case-sensitive default model value. |
| `agents` | no | Ordered default agent IDs. |
| `nodes` | yes | Node ID to node-definition map; an empty map is valid. |
| `entrypoints` | no | Declared midstream scopes and their required evidence. |
| `recovery` | no | `{enabled: false, max_retries: 2}` by default. `max_retries` accepts `1` or `2`. |
| `repairs` | no | Stage ID to a fix-and-verify policy. See [Stage repair rules](#stage-repair-rules). |

Node and input IDs match `^[a-z][a-z0-9_]*$`. A node accepts `needs`, `if`,
`timeout`, and `on_timeout` in addition to its type-specific fields. `needs` is
an ordered list of sibling node IDs. Expressions and edge targets are checked
when the graph is compiled.

Durations contain digits followed by `ms`, `s`, `m`, or `h`: `250ms`, `30s`,
`5m`, and `2h` are valid. There is no implicit unit.
Loop and subworkflow deadlines also bound their nested attempts. A timeout
while a node is running fails that attempt; `on_timeout` is taken when a
`human_wait` deadline expires while waiting.

## Automatic recovery

Set `recovery: {enabled: true}` to retry eligible failed agent steps without an
owner action. Each step gets at most two additional attempts over the run's
lifetime. Set `max_retries: 1` for one additional attempt. Agent nodes can opt
out with `auto_retry: false`; they allow retries by default when the workflow
policy is enabled. An omitted policy uses the saved project or global default;
recovery remains off when no such default has been configured.
The root workflow's policy applies to agent steps in loops and subworkflows;
use the child agent's `auto_retry` field for an individual opt-out.

Relay retries invalid reports, commit or cleanliness errors, timeouts, and
protocol failures. Authentication, permissions, model availability, unsafe
paths, storage, preservation, and Git recovery errors stop for inspection.
Provider limits follow the separate confirmed-reset schedule. Neither policy
changes the assigned model, effort, permissions, or original instructions.

The same agent receives the error and a bounded repair instruction after its
original instructions. Rejected reports and successful upstream report
handoffs remain available. A failed command needs its existing workflow repair
route; Relay does not choose a repair agent for a standalone command. Declared
human waits still require the owner. See
[Automatic step recovery](execution.md#automatic-step-recovery).

## Stage repair rules

Configure `repairs` on an agent or command stage that produces a verdict. Relay
runs the stage first. If its declared output equals `accepted_value`, work
continues. Otherwise Relay runs the configured fixer, then the verifier. A
rejected verification starts another round; an accepted verification releases
dependent stages. Exhausting the budget fails with `repair_exhausted`.

Each rule requires `accepted_output`, `fix`, and `verify`. The source and
verifier must declare that output. `accepted_value` defaults to the string
`"Yes"`; comparison preserves JSON kinds and case. For example, the string
`"Yes"` accepts `"Yes"` but rejects `"yes"`, and the boolean `true` rejects the
number `1`. Numeric values `1` and `1.0` match. `enabled` defaults to `true`.
`max_rounds` defaults to four and
accepts integers from one through 100. A disabled rule adds no execution gate.

Fixers and verifiers are ordinary `agent` or `command` definitions with their
own prompts, outputs, write permissions, model, effort, and permission mode.
They cannot set `needs`, `if`, or `on_timeout`; Relay owns their ordering.
`fix_instruction` and `verify_instruction` have defaults that preserve scope
and require fresh evidence. Custom instructions replace those defaults. Agent
roles receive their instruction and rejection context after their original
prompts. Commands execute their configured argument vector.

Use a required retained selector such as `label`, `json_path`, or `yaml_path`
for a report. `exists` tests only presence and retains no report. Relay keeps
the original rejection and every round's reports. Dependent expressions see
the accepted verifier's outputs under the original stage name; recorded
source outputs remain unchanged. In the example, `needs.review.outputs.ready`
can become `"Yes"` for delivery while the first review still records `"No"`.

<!-- relay-example: valid stage-repairs -->
```yaml
version: 1
name: Review with automatic repairs
model: exact-model-value
agents: [codex]
nodes:
  review:
    type: agent
    prompts: [{local: prompts/review.md}]
    writes: true
    allow_no_commit: true
    outputs:
      ready: {label: {artifact: REVIEW.md, label: Ready}}
  deliver:
    type: command
    needs: [review]
    if: '${{ needs.review.outputs.ready == "Yes" }}'
    run: [git, status, --short]
repairs:
  review:
    accepted_output: ready
    accepted_value: "Yes"
    max_rounds: 4
    fix:
      type: agent
      writes: true
      allow_no_commit: true
    verify:
      type: agent
      writes: true
      allow_no_commit: true
      outputs:
        ready:
          label:
            artifact: REVIEW_FIX_VERIFICATION.md
            label: Ready
```

Rules apply to root workflows and loaded subworkflows. Embedded loop bodies
keep their explicit graphs. Relay reserves the generated node ID
`relay_repair_<stage>`; a conflicting source ID fails validation. The portable
YAML keeps the rule, while the captured graph contains durable coordinators.
The browser shows the original stages and a separate Repairs panel.

Pausing, restarting, or recovering a failed role preserves completed rounds
and the frozen policy. Action failures use the existing failure and recovery
rules; they do not count as accepted verdicts or replenish the repair budget.
See [Execution](execution.md#stage-repair-rules).

## Starter workflows

**Get started** and **New workflow** offer six starters. Each needs one
compatible coding agent. Choose an exact available model before launch; no
template pins a provider model or changes permission defaults. The gallery
copies the chosen YAML and prompts byte-for-byte into the project's `.relay`
folders. Runs use these saved files, which remain editable and uncommitted.
Existing owner files are never replaced.

| Starter | Jobs | Sample input |
| --- | --- | --- |
| Ask an agent | One read-only agent | Explain the repository and its main code |
| Plan, approve, implement | Read-only plan, owner approval, implementation | Explain the main code folder in the README |
| Implement and test | Implementation, test-command choice, pytest or npm test | Improve the README's code-folder explanation |
| Review my branch | Agent report with a `Ready` output | Review for bugs and missing tests |
| Fix until tests pass | Implementation, pytest, bounded fix and verification | Fix test failures without changing their intent |
| Write docs for a change | Documentation agent | Document how to run tests |

All starters define a typed `task` input with a sample default.
**Implement and test** also has a `test_runner` enum, `pytest` or `npm`.
Its command jobs run `python -m pytest` or `npm test` as argument vectors.
The project must already provide the selected test command and dependencies.

**Review my branch** has `writes: true` and `allow_no_commit: true`, because
a read-only job cannot create its required report. Its instructions permit
only `REVIEW.md` and forbid code edits and commits. The `Ready` label supplies
a retained verdict. This instruction does not add a new runtime permission.

**Fix until tests pass** records pytest's exit code and boolean verdict in
`AUDIT_CHECKPOINT.json`. The test job returns that verdict to the existing
repair policy, allowing a test failure to start the configured fixer rather
than fail the run immediately. The verifier repeats the same command. At most
two repair rounds run; passing tests accept `ready: true`. Each command uses
an argument vector with `shell=False`. Neither starter installs dependencies.

## Typed inputs

Each input has `type`, optional `description`, optional `required`, optional
`default`, and type-specific `constraints`.

| Type | Constraints |
| --- | --- |
| `string` | `min_length`, `max_length`, and `pattern` |
| `integer` | `min` and `max` |
| `number` | `min` and `max` |
| `boolean` | none |
| `enum` | non-empty, unique `values` |

Input validation is strict: Relay does not turn the string `"4"` into the
integer `4`. String patterns compile through Pydantic's linear-time,
RE2-compatible regex engine. Unknown inputs and all independent input errors
are reported together.

```text
inputs:
  target:
    type: string
    required: true
    constraints:
      min_length: 2
      max_length: 40
      pattern: '^[a-z][a-z0-9-]+$'
  passes:
    type: integer
    default: 2
    constraints: {min: 1, max: 5}
  mode:
    type: enum
    default: review
    constraints:
      values: [review, implement]
```

## Agent nodes

An `agent` node receives ordered static prompts plus launch inputs, run
metadata, and named upstream outputs as separate values. It may set an exact
`model`, an ordered `agents` preference, per-tool `agent_options`, a legacy
`permission_profile`, declared
`outputs`, and `writes: true`. A writing node may set `allow_no_commit: true`
when a verified no-op is a successful outcome. Relay does not append previous
transcripts.

<!-- relay-example: valid agent -->
```yaml
version: 1
name: Agent review
model: exact-model-value
agents: [codex]
nodes:
  review:
    type: agent
    prompts:
      - local: prompts/review.md
    agent_options:
      codex:
        effort: high
        permission_mode: workspace-write
    outputs:
      ready:
        label:
          artifact: report.md
          label: Ready
```

`agent_options` is keyed by agent ID. Each tool accepts optional `effort` and
`permission_mode` strings, using the exact values advertised for the selected
model. Omit either key to inherit saved project or global choices for that
exact model, or the provider's default when none is configured. Use an explicit
null to keep the provider's default even when a saved override exists. Browser
labels are never serialized as option values. Empty strings and unknown option
fields are invalid. The editor removes a key when the owner chooses to inherit
and removes empty option mappings.

Launch preflight checks each candidate's own overrides after selecting the
exact model. A candidate must confirm every requested value before its route
is frozen. Two nodes can use the same model with different effort or mode
values. The worker applies the frozen values in a fresh session before sending
the prompt and rejects unsupported or changed values. Existing workflows that
omit `agent_options` use provider defaults until the owner configures defaults
in Settings.

This invalid workflow attempts to leave the project prompt root.

<!-- relay-example: invalid agent-prompt-escape -->
```yaml
version: 1
name: Escaping prompt
model: exact-model-value
agents: [codex]
nodes:
  review:
    type: agent
    prompts:
      - local: ../secret.md
```

## Command nodes

A `command` node requires a non-empty argument vector. Relay invokes it with
`shell=False` in the node worktree. For example, `[git, status, --short]`
becomes three process arguments exactly as written; Relay performs no shell
splitting or platform-specific quoting. `env` entries override inherited
environment values. `writes` and `outputs` have the same meaning as on an
agent node, including the explicit `allow_no_commit` exception.

<!-- relay-example: valid command -->
```yaml
version: 1
name: Command check
nodes:
  status:
    type: command
    run: [git, status, --short]
    env:
      RELAY_CHECK: enabled
```

A scalar command is invalid because its argument boundaries are unknown.

<!-- relay-example: invalid command-scalar -->
```yaml
version: 1
name: Invalid command
nodes:
  status:
    type: command
    run: git status --short
```

## Human-wait nodes

A `human_wait` node records a question for the owner. `deadline` is optional;
without it the wait is indefinite. A timed wait may name an `on_timeout`
target. The response is correlated to the current node attempt.

<!-- relay-example: valid human-wait -->
```yaml
version: 1
name: Approval
nodes:
  approve:
    type: human_wait
    prompt: Continue with the implementation?
    deadline: 15m
    on_timeout: stop
  stop:
    type: command
    needs: [approve]
    run: [python, -c, "print('stopped')"]
```

The word `later` is not a duration.

<!-- relay-example: invalid human-wait-duration -->
```yaml
version: 1
name: Invalid approval
nodes:
  approve:
    type: human_wait
    prompt: Continue?
    deadline: later
```

## Condition nodes

A `condition` evaluates `expr` and selects the matching key in `branches`.
Quote YAML keys such as `"true"` and `"false"`; unquoted keys are booleans in
YAML 1.1 and fail Relay's string-key schema. Branch target nodes normally name
the condition in `needs`, allowing the scheduler to skip the unselected path.

<!-- relay-example: valid condition -->
```yaml
version: 1
name: Conditional path
inputs:
  mode:
    type: enum
    default: review
    constraints:
      values: [review, implement]
nodes:
  choose:
    type: condition
    expr: "${{ inputs.mode }}"
    branches:
      review: review_path
      implement: implement_path
  review_path:
    type: command
    needs: [choose]
    run: [python, -c, "print('review')"]
  implement_path:
    type: command
    needs: [choose]
    run: [python, -c, "print('implement')"]
```

Function calls are outside the expression language.

<!-- relay-example: invalid condition-call -->
```yaml
version: 1
name: Unsafe expression
nodes:
  choose:
    type: condition
    expr: "${{ __import__('os') }}"
    branches:
      yes: done
  done:
    type: command
    needs: [choose]
    run: [python, -c, "print('done')"]
```

## Loop nodes

A `loop` contains its own node map. It runs at most `max_iterations`; the value
must be between 1 and 100. Relay evaluates `until` after each iteration. If it
never becomes true, Relay selects the required `exhausted` edge. The maximum
expanded workflow, including nested loops and subworkflows, is 10,000 node
instances so individually valid loop bounds cannot create impractical work.

<!-- relay-example: valid loop -->
```yaml
version: 1
name: Bounded inspection
nodes:
  inspect:
    type: loop
    max_iterations: 3
    until: "${{ loop.index >= 2 }}"
    exhausted: fallback
    body:
      status:
        type: command
        run: [git, status, --short]
  fallback:
    type: command
    needs: [inspect]
    run: [python, -c, "print('limit reached')"]
```

This loop exceeds the fixed expansion bound.

<!-- relay-example: invalid loop-bound -->
```yaml
version: 1
name: Unbounded work
nodes:
  inspect:
    type: loop
    max_iterations: 101
    exhausted: fallback
    body:
      status:
        type: command
        run: [git, status, --short]
  fallback:
    type: command
    needs: [inspect]
    run: [python, -c, "print('limit reached')"]
```

## Subworkflow nodes

A `subworkflow` runs another file inside the same run. Child execution is inline
while work is runnable. A nested human wait releases the worker; answering it
resumes the same parent attempt from durable child state. The
reference `child` resolves to `.relay/workflows/child.yaml`; `child.yml` or
`nested/child.yaml` keeps its explicit suffix and relative path. Resolution
uses relative POSIX keys on Linux and Windows: empty segments, backslashes,
`.` and `..` are rejected. References cannot leave `.relay/workflows/`, and
recursive references fail validation.
Inputs are explicit. Each parent output names a child output as
`<child-node>.<output>`. Relay evaluates parent expressions, applies the child
input defaults, and validates the resulting values against the child's typed
input contract before materializing its scope.

<!-- relay-example: valid subworkflow -->
```yaml
version: 1
name: Child invocation
nodes:
  verify:
    type: subworkflow
    workflow: child
    inputs:
      target: relay
    outputs:
      ready: check.ready
```

A missing child is invalid before a run is created.

<!-- relay-example: invalid subworkflow-missing -->
```yaml
version: 1
name: Missing child
nodes:
  verify:
    type: subworkflow
    workflow: missing-child
```

## Dependencies and expressions

Relay compiles data and control edges with Kahn's topological algorithm in
`O(V + E)` time.
All referenced dependency, branch, timeout, and exhausted targets must exist.
The top-level graph and every loop body must be acyclic across both kinds of
edge. A branch, timeout, or exhausted edge cannot point to its own source or
back to an upstream node.

<!-- relay-example: invalid control-cycle -->
```yaml
version: 1
name: Cyclic branch
nodes:
  build:
    type: command
    run: [git, status]
  choose:
    type: condition
    needs: [build]
    expr: "${{ True }}"
    branches:
      "true": build
```

Expressions use the exact `${{ ... }}` wrapper. They can read only these
mappings:

- `inputs.<name>`
- `needs.<node>.outputs.<name>`
- `run.<meta>`
- `loop.<index>`

Supported operations are mapping attribute or item access, literal lists,
tuples, sets, and maps, equality and ordered comparisons, `in` and `not in`,
`and`, `or`, `not`, and unary numeric signs. Calls, comprehensions, arbitrary
object attributes, dunder access, and Python `eval` are not available.

## Prompts

Prompt lists preserve their order and file bytes. A local reference such as
`prompts/review.md` resolves to `<repo>/.relay/prompts/review.md`. A global
reference such as `coding/review.md` resolves to
`<config>/prompts/coding/review.md`. Both paths are resolved through symlinks
and rejected if the result leaves the allowed root.

```text
prompts:
  - local: prompts/review.md
  - global: coding/review.md
```

Prompt Markdown is static. Relay does not replace braces, environment-variable
syntax, or other text inside a prompt. Launch inputs, run metadata, and
upstream outputs travel as separate agent context blocks.

## Outputs

Agent and command outputs use one selector per name:

```text
outputs:
  report_exists:
    exists: reports/result.md
  readiness:
    label:
      artifact: reports/result.md
      label: Ready for implementation
  json_status:
    json_path:
      artifact: reports/result.json
      path: build.status
  yaml_status:
    yaml_path:
      artifact: reports/result.yaml
      path: build.status
```

For `{exists: "reports/result.md"}`, Relay returns a boolean. A label selector
reads the text after the first exact line prefix; `Ready: Yes` becomes `Yes`
for label `Ready`, while `ready: Yes` does not match. A dotted data path walks
mapping keys only: `build.status` reads key `build`, then key `status`.
Missing files, labels, or keys fail the node with `output_invalid`.

Every artifact path is resolved beneath the node worktree after following
symlinks. Selectors cannot read a file outside that worktree.

Files named by `label`, `json_path`, and `yaml_path` selectors are also the
node's required retained artifacts. Relay preserves each file and its SHA-256
hash before removing an attempt worktree. An `exists` selector is only a
boolean check: `false` is a valid output, so that path is not a required file.

### Required handoffs and automatic gates

An agent can finish its turn after reporting a blocker. A dependency in `needs`
waits for the node's execution result; it does not check that the agent completed
the requested work. Declare a required artifact with a `label`, `json_path`, or
`yaml_path` selector before handing work to the next node. A missing artifact or
field then fails the producer and blocks its dependents automatically. An
`exists` selector alone does not enforce this requirement.

Use a condition to advance on an explicit verification result. This example
expects the report to contain exactly `Ready: Yes` or `Ready: No`. Keep generated
reports in an ignored repository path when they must remain uncommitted; writer
nodes still have to leave code and the Git index clean. Root workflow reports
can remain unstaged; see [Git checks](git-and-artifacts.md#clean-launch).

<!-- relay-example: valid required-handoff -->
```yaml
version: 1
name: Required report and readiness gate
nodes:
  verify:
    type: agent
    writes: true
    allow_no_commit: true
    prompts:
      - local: prompts/review.md
    outputs:
      ready:
        label:
          artifact: report.md
          label: Ready
  gate:
    type: condition
    needs: [verify]
    expr: "${{ needs.verify.outputs.ready == 'Yes' }}"
    branches:
      "true": proceed
      "false": blocked
  proceed:
    type: command
    needs: [gate]
    run: [python, -c, "print('Verification passed')"]
  blocked:
    type: human_wait
    needs: [gate]
    prompt: Review the failed verification before deciding the next step.
```

For handoffs without a stable field, add a command node that validates the
required files and exits nonzero when a file is missing or empty. If those files
are ignored and shared between phases, that command needs `writes: true` and
`allow_no_commit: true` to use the primary worktree. Read-only nodes use separate
worktrees and cannot see another node's uncommitted files. Reserve `human_wait`
for decisions that require an owner, rather than checks a command or condition
can perform.

## Scope paths

Every runtime node has an unambiguous scope path:

| Definition | Runtime scope | Parent scope |
| --- | --- | --- |
| Top-level node `review` | `root.review` | none |
| Loop `build_loop`, iteration 2 | `root.build_loop#2` | `root` |
| Subworkflow `verify` in that iteration | `root.build_loop#2.verify` | `root.build_loop#2` |
| Child node `check` | `root.build_loop#2.verify.check` | `root.build_loop#2.verify` |

Loop indexes are one-based. Node IDs cannot contain `.` or `#`, so parsing is
deterministic. `needs.<id>` resolves to the same enclosing scope; from
`root.build_loop#2.verify.check`, sibling `format` becomes
`root.build_loop#2.verify.format`.

Relay eagerly compiles route keys for every possible bounded loop iteration
and transitive subworkflow instance. Runtime node rows remain scoped, and
execution can stop before unused loop instances are materialized.

For example, iteration 2 of loop `build_loop` can contain subworkflow `verify`
and its child `check`:

```text
root.build_loop#2
root.build_loop#2.verify
root.build_loop#2.verify.check
```

If `verify` maps child output `check.ready` to `ready`, the loop body reads it
as `needs.verify.outputs.ready`. Relay resolves that reference only inside
`root.build_loop#2`; output values do not cross iteration boundaries.

## Midstream entry points

An entry point names a `scope_path`, required launch input IDs, and retained
artifact evidence. Artifact hashes are lowercase SHA-256 values.

```text
entrypoints:
  - scope_path: root.implement
    inputs: [target]
    artifacts:
      approved_plan:
        path: artifacts/plan.md
        sha256: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef
```

Before a midstream launch, Relay validates the inputs and confirms that every
artifact exists with the recorded hash. No run row is created when this
preflight fails.

## Snapshots and routing

Launch captures the exact root YAML, every transitive child YAML, ordered
prompt content and hashes, typed inputs, route table, agent preferences, Relay
version, and runtime versions. SHA-256 hashing uses the UTF-8 bytes as read;
Relay does not deduplicate snapshots or mutate one after creation.

An agent route is keyed by runtime scope, not only by model. Model values are
exact and case-sensitive. Candidate order concatenates node preferences,
workflow preferences, then owner preferences while removing later duplicates.
For example, node `[codex, cursor]`, workflow `[cursor, claude]`, and owner
`[codex, copilot]` becomes `[codex, cursor, claude, copilot]`. A later model
preflight records the first candidate that proves it can select the exact
value; there is no automatic model fallback.

## Installation defaults

[Settings](projects-and-storage.md#global-defaults-and-project-overrides) can
supply models, agent order, provider options, job timeouts, retry participation,
and recovery fields omitted from a workflow. Job models still win over run
model overrides, which win over workflow models. Defaults come afterwards.
Explicit job effort/permission values remain exact; `null` keeps that option
at the agent's default and skips project/global inheritance.

`timeout: null` skips an inherited agent/command timeout. Human waits retain
only their declared deadlines. Recovery fields inherit individually, so an
explicit `enabled: false` keeps automatic recovery off.
Saved repair rounds and instructions are unchanged; global repair defaults
initialize new rules in the editor only. Workflow schema version 1 is unchanged.

Launch retains original YAML and prompt bytes while freezing resolved node
definitions, recovery, and provider routes. Snapshots additionally record
`launch_defaults`; captured child records include their resolved `definition`
alongside original YAML and hash. Older snapshots keep an empty defaults record
and continue reading their original child YAML. Updating settings never
rewrites an existing snapshot, source workflow, or completed job.
