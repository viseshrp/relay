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

Node and input IDs match `^[a-z][a-z0-9_]*$`. A node accepts `needs`, `if`,
`timeout`, and `on_timeout` in addition to its type-specific fields. `needs` is
an ordered list of sibling node IDs. Expressions and edge targets are checked
when the graph is compiled.

Durations contain digits followed by `ms`, `s`, `m`, or `h`: `250ms`, `30s`,
`5m`, and `2h` are valid. There is no implicit unit.

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
`model`, an ordered `agents` preference, a `permission_profile`, declared
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
    outputs:
      ready:
        label:
          artifact: report.md
          label: Ready
```

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

A `subworkflow` runs another file synchronously inside the same run. The
reference `child` resolves to `.relay/workflows/child.yaml`; `child.yml` or
`nested/child.yaml` keeps its explicit suffix and relative path. Resolution
cannot leave `.relay/workflows/`, and recursive references fail validation.
Inputs are explicit. Each parent output names a child output as
`<child-node>.<output>`.

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

Relay compiles `needs` with Kahn's topological algorithm in `O(V + E)` time.
All referenced dependency, branch, timeout, and exhausted targets must exist.
The top-level graph and every loop body must be acyclic.

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
