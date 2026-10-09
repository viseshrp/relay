# Workflows

Relay saves workflow YAML under `.relay/workflows/`. Its public language uses
GitHub Actions jobs, ordered steps, expressions, and hyphenated field names.
Jobs run serially on this computer in one cumulative run worktree. Agents,
owner decisions, reports, artifacts, and caches use local `relay/...@v1`
actions. These files require Relay to execute.

Relay owns the accepted schema, derived from MIT-licensed GitHub syntax.
Only fields with local behavior are accepted; unknown fields are rejected.
`GET /api/workflow-language` returns the support manifest. Validation reads
sources without starting processes or retrieving credentials. See
[local language audit](workflow-language-compatibility.md) for provenance,
limits, and the implementation map.

Saved workflow sources and new launches require `jobs` and ordered `steps`.
The previous `version: 1` / `nodes` authoring format is unsupported. Replace old
files with current sources; Relay does not provide a conversion-preview flow.
Captured run snapshots remain available in run history.

## Jobs and ordered steps

<!-- relay-example: valid ordered-steps -->
```yaml
name: Check the repository
run-name: Check ${{ inputs.task }}
on:
  workflow_dispatch:
    inputs:
      task: {type: string, required: true, default: Inspect the repository}
defaults:
  run: {shell: python}
jobs:
  main:
    name: Repository checks
    timeout-minutes: 15
    steps:
      - id: inspect
        run: |
          import subprocess
          subprocess.run(['git', 'status', '--short'], check=True)
      - uses: relay/command@v1
        with: {argv: '["git", "diff", "--check"]'}
```

The root accepts `name`, `description`, `run-name`, `on`, `env`, `defaults`,
`concurrency`, `cache-mode`, and `jobs`. A job accepts `name`, `needs`, `if`,
`strategy`, `env`, `defaults`, `outputs`, `environment`, `concurrency`,
`cache-mode`, `timeout-minutes`, `continue-on-error`, and `steps`; a reusable
job uses `uses`, `with`, and `secrets` instead of steps. Every job runs on this
computer. There is no runner selection or parallelism field. Removed fields
are rejected, including `runs-on`, `max-parallel`, and environment `deployment`.

Steps accept `id`, `name`, `if`, `env`, `timeout-minutes`,
`continue-on-error`, and either `run` with `shell` and `working-directory`,
or `uses` with `with`. IDs match `^[A-Za-z_][A-Za-z0-9_-]*$` and are unique
within their scope. `needs` names a sibling job or a list of sibling jobs.
Dependency cycles fail validation. Ready siblings run in source order.
Display names can use expressions; IDs remain stable.

Every physical job uses the primary run worktree. Steps edit, test, and then
commit in that same directory. A successful job with code changes must finish
with a descendant commit and a clean index and code worktree. A clean no-op is
valid. An individual agent step need not commit. Accepted job B starts at
accepted job A's head. Failed-job bytes and evidence are retained before later
jobs continue from the last accepted head. The source checkout is never reset
or checked out. See [Git and evidence](git-and-artifacts.md#actions-job-boundaries).

An installation-wide durable lease admits one Actions job, including its
matrix and nested children, at a time.
Containers, services, background processes, remote actions, hosted runners,
and YAML `permissions` are unsupported. Provider permissions remain owner
administration settings.

## Scripts and command actions

`run` accepts a string or block scalar. Relay writes a private script file and
starts the interpreter with an argument vector and `shell=False`. Shells are
`bash`, `sh`, `pwsh`, `powershell`, `cmd`, `python`, or an installed custom
interpreter command containing `{0}` for the script path. The default is the
platform's ordinary script shell. Workflow and job `defaults.run` provide a
shell and working directory; step values override them. Working directories
must resolve inside the run workspace.

`relay/command@v1` requires exactly one of `argv` (a JSON string containing a
nonempty argument vector) or `command` (an owner-configured command name).
Arguments are never reinterpreted as shell syntax. Relay owns process groups
or Windows Job Objects and performs bounded shutdown on cancellation/timeout.

<!-- relay-example: valid explicit-command -->
```yaml
jobs:
  check:
    steps:
      - uses: relay/command@v1
        with: {argv: '["python", "-m", "pytest"]'}
      - shell: python
        run: |
          import subprocess
          subprocess.run(['git', 'add', '--all'], check=True)
          changed = subprocess.run(
              ['git', 'diff', '--cached', '--quiet'], check=False
          ).returncode
          if changed:
              subprocess.run(['git', 'commit', '-m', 'Apply changes'],
                             check=True)
```

Commit only the changes intended by the workflow. This example belongs to an
isolated run job and does not authorize staging unrelated owner changes.

## Inputs

`on.workflow_dispatch.inputs` declares `type`, `description`, `required`, and
`default`. Types are `string`, `boolean`, `number`, `choice` with `options`,
and `environment`. The browser provides typed controls and configured
environment choices. `inputs` and the manual event payload preserve JSON
types. Unknown supplied names and invalid defaults fail validation.
Input counts are bounded by the YAML size/node limits; resolved inputs must
fit within 65,535 bytes. There is no separate hosted-service field count.

`on.workflow_call.inputs` supports `string`, `boolean`, and `number`.
`relay/validate-input@v1` provides explicit constraints: `value`, `type`, and
JSON `constraints`, using Relay's string, integer, number, boolean, or enum
validators. It exports string `value` and `valid` outputs.

<!-- relay-example: valid typed-dispatch -->
```yaml
on:
  workflow_dispatch:
    inputs:
      task: {type: string, required: true}
      apply: {type: boolean, default: false}
      rounds: {type: number, default: 2}
      target: {type: choice, options: [docs, tests], default: docs}
jobs:
  show:
    steps:
      - env: {TASK: '${{ inputs.task }}'}
        run: echo "$TASK"
```

## Expressions and conditions

Use `${{ ... }}` for interpolation. `if` also accepts a bare expression.
String literals use single quotes; two single quotes escape a quote.
Literals include boolean, null, decimal, hexadecimal, and exponent numbers.
Operators are `!`, comparisons, `==`, `!=`, `&&`, and `||`, with grouping,
property access, indexing, and `*` object/array filters. Missing properties
yield the empty value. Equality follows Actions' loose numeric coercion and
case-insensitive string comparison. Logical operators return the selected
operand rather than forcing a boolean.

Functions are `contains`, `startsWith`, `endsWith`, `format`, `join`,
`toJSON`, `fromJSON`, `hashFiles`, `case`, `success`, `failure`, `cancelled`,
and `always`. `case(condition, value, ..., fallback)` selects the first match.
`hashFiles` hashes matching workspace file contents and yields an empty string
when nothing matches. Bounded globs never follow links or read `.git`.

Contexts are checked per field:

| Context | Contents |
| --- | --- |
| `relay` | Local event, repository, ref/SHA, workflow and run identity; no GitHub token or remote API |
| `inputs` | Typed manual/reusable inputs |
| `vars` | Frozen installation, project, and approved environment variables |
| `env` | Workflow, job, and current step environment |
| `secrets` | Current scope's resolved bindings, after environment gates |
| `needs` | Direct dependency jobs' string outputs and effective result |
| `steps` | Completed named steps' string outputs, raw outcome, and conclusion |
| `jobs` | Reusable workflow output evaluation |
| `matrix`, `strategy` | Current serial variant, index, total, and strategy |
| `job`, `host` | Local status, OS, architecture, and private resource paths |

`if` defaults to `success()`. Failed steps skip later ordinary steps;
`failure()` or `always()` admits follow-up steps. Failed jobs do not stop
unrelated jobs. Dependents require successful dependencies unless their
condition explicitly admits another result.

`continue-on-error` preserves raw `outcome: failure` and changes effective
`conclusion` to `success`. Status checks use conclusions. Tolerating a job
failure does not accept its failed workspace as a new checkpoint.

<!-- relay-example: valid failure-followup -->
```yaml
jobs:
  check:
    steps:
      - id: test
        continue-on-error: true
        uses: relay/command@v1
        with: {argv: '["python", "-m", "pytest"]'}
      - if: steps.test.outcome == 'failure'
        run: echo Tests need repair
      - if: always()
        run: echo Check completed
```

`timeout-minutes` must be greater than zero and at most 360, including resolved
expressions. Jobs default to 360 minutes. Persisted deadlines bound descendants
and survive suspension, restart, and retry. A step cannot extend its job's
deadline. A timed-out step records failure, including when its deadline
expires before execution starts. Eligible follow-ups can run within the
remaining job deadline. `continue-on-error` applies to this failure too.

## Agent nodes

`relay/agent@v1` accepts `agent` or ordered JSON `agents`, `model`, `effort`,
newline-separated `prompt-files`, `prompt`, and optional `report`, `selector`,
`format`, `field`, `label`, and `auto-retry`. Local prompt paths resolve under
`.relay/`; `global:NAME` resolves in the owner's global prompt directory.
A runtime `prompt` follows the frozen ordered prompt files.

<!-- relay-example: valid local-agent -->
```yaml
on:
  workflow_dispatch:
    inputs:
      task: {type: string, required: true}
jobs:
  review:
    steps:
      - id: inspect
        uses: relay/agent@v1
        with:
          agents: '["codex", "claude"]'
          model: exact-model-value
          prompt-files: prompts/review.md
          prompt: ${{ inputs.task }}
          report: REVIEW.md
          format: label
          label: Ready
          auto-retry: false
```

Routes, exact model/effort values, and prompt references must resolve from
launch-static inputs, variables, local `relay` context, and static matrix
values. Runtime outputs, secrets, and dynamic matrices cannot choose a route.
Omitting `with.effort` inherits saved settings for the exact model. Explicit
`effort: null` or an empty string preserves the provider's own default and
suppresses saved effort overrides. The editor offers both choices when saved
defaults apply. A different explicit value requires fresh provider support.
Relay freezes transitive routes and prompt bytes and requires fresh exact model
selection at launch and execution. It never changes provider, model, effort,
or approval settings to bypass a failure. Agent steps may edit code and defer
the commit until their job ends. Transport remains ACP for Codex, Claude Code,
Copilot CLI, and Cursor CLI; Antigravity uses its native headless adapter.

## Automatic recovery

The owner can enable bounded recovery in defaults or an active run's controls.
`with.auto-retry: true` explicitly enables bounded agent repair; `false` opts
that step out. Omission follows the run policy. Eligible report, protocol, and
timeout failures retain rejected evidence and append a separate repair
instruction after original prompts. The budget is durable over the step's
lifetime and is never replenished by restart or owner retry. Completed
upstream work, exact routes, and original prompt bytes remain frozen.

Authentication, model drift, unsafe paths, preservation failures, and missing
permissions require inspection. Usage recovery also requires a structured
provider confirmation of a future reset. Prose and cached usage observations
do not authorize retry. A human wait remains an owner decision. See
[execution recovery](execution.md#automatic-step-recovery).

## Stage repair rules

Use ordered test/report, repair, and verification steps with raw outcome
conditions for a fixed number of repair rounds. **Fix until tests pass** uses
two repair rounds and commits after verification. For a reusable repair body,
`relay/loop@v1` accepts `workflow`, JSON `inputs`, `max-iterations` from 1
through 100, `until-output`, and `equals`. Every iteration is a durable serial
scope. Exhausting the budget fails the loop.

Historical `repairs`, embedded loop bodies, switch nodes, and entrypoint graphs
remain readable in legacy captured runs. They are not public Actions keys and
are not silently converted to a different repair contract.

## Human waits

`relay/human-wait@v1` accepts a rendered `prompt` and optional
`timeout-minutes`. It creates one durable interaction on the current step
attempt and exports `steps.ID.outputs.answer`. Restart preserves that request
and completed steps. Duplicate, stale, expired, or mismatched responses cannot
resume another attempt.

<!-- relay-example: valid owner-answer -->
```yaml
jobs:
  main:
    steps:
      - id: approval
        uses: relay/human-wait@v1
        with:
          prompt: Review the change. Type Approved to continue.
          timeout-minutes: 30
      - if: steps.approval.outputs.answer == 'Approved'
        run: echo Approved
```

## Outputs and file commands

Step outputs are strings, including typed report values. Typed values remain
in private execution state. Jobs export expression values; reusable workflows
export `on.workflow_call.outputs.NAME.value` from their jobs. Limits are 1 MiB
per step/job and 50 MiB across job exports per run, measured in UTF-16.
Secret-bearing job exports are skipped with a warning.

Scripts receive private `RELAY_OUTPUT`, `RELAY_ENV`, `RELAY_PATH`,
`RELAY_STATE`, `RELAY_STEP_SUMMARY`, and `RELAY_ARTIFACTS` paths. Each file
is consumed once and limited to 1 MiB. UTF-8, a UTF-8 BOM, LF, and CRLF are
accepted. Key/value files support `name=value` and multiline
`name<<DELIMITER` records. NULs, malformed records, and linked files fail.

<!-- relay-example: valid file-outputs -->
```yaml
jobs:
  main:
    outputs:
      answer: ${{ steps.capture.outputs.answer }}
    steps:
      - id: capture
        shell: python
        run: |
          import os
          from pathlib import Path
          Path(os.environ['RELAY_OUTPUT']).write_text('answer=ready\n')
          Path(os.environ['RELAY_ENV']).write_text('NEXT_VALUE=ready\n')
          Path(os.environ['RELAY_STEP_SUMMARY']).write_text('# Checked\n')
      - shell: python
        run: |
          import os
          assert os.environ['NEXT_VALUE'] == 'ready'
```

`RELAY_ENV` changes subsequent steps and cannot replace `RELAY_*`
or `NODE_OPTIONS`. `RELAY_PATH` prepends later search paths.
`RELAY_STATE` supplies `STATE_*` only to the registering JavaScript action's
post hook. File state stays local to its owning job.

Command/JavaScript logs recognize `::warning::`, `::error::`, `::notice::`,
`::debug::`, `::group::`, `::endgroup::`, `::add-mask::`, and
`::stop-commands::TOKEN` / `::TOKEN::`. Annotation properties are file, line,
endLine, col, endColumn, and title. Percent escapes are decoded. Agent prose is
never interpreted as commands. Secrets and added masks are removed before
logs, summaries, annotations, and outputs enter public events, including
secrets split across stream chunks.

`relay/validate-report@v1` accepts `path` or `report`, `format` (`label`,
`json`, `yaml`, or `exists`), and `label` or `field`. Alternatively supply a
JSON `selector` with retained `label`, `json_path`, or `yaml_path` selectors.
It exports `value`. Required selectors retain exact bytes; `exists` returns a
boolean string and does not require or retain a report. A successful agent
turn alone does not establish a required report or verdict.

## Artifacts and caches

`relay/upload-artifact@v1` accepts newline-separated glob `path`, optional
`name` (default `artifact`), and `retention-days` from 0 through 365. Zero
retains the named product without automatic expiry. Names are immutable within
a run. Outputs are `artifact-id` and `artifact-digest`.
`relay/download-artifact@v1` accepts `name`, optional `run-id`, and workspace
`path`; it verifies hashes and reads only the same project's artifacts. The
browser offers verified ZIP downloads, names, digests, sizes, and expiry.

Products have hashed manifests, ownership markers, and limits of 10,000 files
and 1 GiB. Linked paths, `.git`, and traversal are rejected. Cache restoration
also rejects `.relay`. Optional product expiry is separate from required
execution evidence and never deletes report or Git preservation.

`RELAY_ARTIFACTS` declares newline-separated local file subjects (`path` or
`file://path`). Comments and blank lines are ignored. A job permits 500 unique
subjects; each file is hashed and retained as evidence. OCI registry digests
are rejected because Relay cannot verify or retain their remote content.
`RELAY_ARTIFACTS_LIST` contains earlier subjects' JSON metadata.

Cache actions accept `key` and newline-separated `path` patterns.
`relay/restore-cache@v1` and `relay/cache@v1` also accept ordered
newline-separated `restore-keys`. Matching uses exact keys, then recent prefix
matches with the same path-derived version and project namespace. Outputs are
`cache-hit`, `cache-primary-key`, and `cache-matched-key`. `relay/cache@v1`
registers a save after job success; `relay/save-cache@v1` saves explicitly.
Entries are immutable. A project has a 10 GiB quota with least-recently-used
eviction after ownership/hash checks.

Workflow/job `cache-mode` is `write` (read and write, default), `read`,
`write-only`, or `none`. Reusable callers can reduce a callee's capabilities;
a callee cannot regain them. Caches never replace required evidence.

## Matrix jobs

`strategy.matrix` accepts static axes, `include`, `exclude`, and a dynamic
object such as `fromJSON(needs.prepare.outputs.matrix)`. Expansion is limited
to 256 variants and frozen before the first variant. Restart reuses that
manifest. `strategy.fail-fast` defaults to true; an effective failed variant
skips remaining pending variants. Set false to continue them.

<!-- relay-example: valid serial-matrix -->
```yaml
jobs:
  check:
    name: Check ${{ matrix.target }}
    strategy:
      fail-fast: false
      matrix:
        target: [docs, tests]
        include:
          - target: docs
            detail: documentation
    steps:
      - env: {TARGET: '${{ matrix.target }}'}
        run: echo "$TARGET"
```

Matrix outputs use the last successful nonempty value per key in serial order,
including reusable matrix calls. Each physical variant has private step state
and its own accepted job checkpoint.

## Reusable workflows and local actions

Reusable jobs use `./.relay/workflows/NAME.yml` or `.yaml`, `with` inputs, and
explicit `secrets` or `inherit`. Callees declare `on.workflow_call`, typed
inputs, required secret names, and expression outputs. Omission does not
inherit secrets. Every nested contract is enforced; approved environment
bindings override passed names for that job. Bounds are ten reusable levels
and fifty unique referenced workflows. Cycles and missing sources fail.

<!-- relay-example: valid reusable-call -->
```yaml
jobs:
  verify:
    uses: ./.relay/workflows/child.yaml
    with: {target: docs}
```

Calls, loops, and local actions freeze all transitive source bytes at launch.
Owner edits cannot change the executing snapshot. Credentials remain
references rather than captured credential values.

Steps can use `./.relay/actions/NAME` with `action.yml` or `action.yaml`.
Metadata accepts `name`, `description`, `inputs`, `outputs`, and `runs`.
Marketplace `branding` and unused `author` fields are rejected. Missing required
or unknown supplied inputs fail. Composite
metadata uses `runs.using: composite`, ordered steps, and expression outputs.
Composite `run` steps require `shell`. Files are frozen in private storage;
`relay.action_path` and `RELAY_ACTION_PATH` identify that directory.

JavaScript metadata uses `runs.using: node20` or `node24`, local `main`, and
optional `post` and `post-if`. The exact installed Node major is required;
Relay does not download it or install dependencies. Bundle dependencies with
the action. `pre` is unsupported. Registered post hooks run in reverse order
with isolated state. Already registered cleanup can run under a separate
bounded deadline after owner stop. Cancellation never authorizes a new
ordinary step or agent turn.

A failed post hook fails its job. Post file commands, declared artifacts, and
summaries use the same validation and masking as main scripts. Cache filesystem
restore/save failures emit warnings; ownership or integrity failures stop the job.

## Variables, secrets, and environments

Workflow settings manage installation, project, and environment bindings.
Project values override installation values; approved environment values
override project values. Each scope permits 100 variables and 100 secrets,
with values limited to 48 KiB. Names are case-insensitive identifiers and
cannot start with `RELAY_`.

Variables freeze by value. Secrets freeze source, reference, and revision and
resolve from either process environment variables or the explicit native
backend: macOS Keychain, Windows Credential Manager, or Linux Secret Service.
Credential operations run in a bounded subprocess with no plaintext fallback.
Secret values are never returned by the binding API or saved in snapshots or
binding rows. Missing bindings fail rather than changing secret source.

Jobs select `environment` as a name or `{name, url}`. Settings provide branch
patterns, optional owner approval, and a wait timer. The gate belongs to the
current job attempt and runs before environment secrets resolve. Generic human
answers cannot approve it. Timer/approval requirements survive restart, and
existing runs retain frozen environment settings.

Environment URLs resolve after the steps finish, so a URL can use a step output.
The run page exposes HTTP(S) links without embedded credentials. URLs containing
registered secrets are omitted.

## Concurrency queues

Workflow/job `concurrency` accepts a string or `{group, cancel-in-progress,
queue}`. Groups use field-specific expression contexts, compare
case-insensitively, and are bounded to 256 characters. Workflow and job queues
have distinct scopes.

Local `queue: single` keeps one pending owner and supersedes older pending
owners. `cancel-in-progress: true` also requests active-owner cancellation.
`queue: max` is FIFO with at most 100 pending owners and cannot combine with
cancel-in-progress. Job cancellation targets that job's descendants; workflow
cancellation targets its run. Nested scopes cannot queue behind their own
active ancestor. Queue reservation precedes the global lease, so queued work
does not hold that lease.

## Local automatic triggers

Declaring an event does not activate it. **Activate EVENT** explicitly
authorizes that trigger's writing jobs on this computer. Activation freezes
source/prompt hashes and binding revisions; changed sources block delivery
until reactivation. Automatic launches still apply normal clean-source,
provider, input, and environment gates. Delivery identities are deduplicated.
Blocked and uncertain launches remain visible for owner review.

`on.schedule` uses POSIX five-field cron, optional IANA `timezone` (UTC by
default), and one-minute resolution. Ranges, lists, steps,
and Sunday 0 or 7 are supported. Day-of-month/day-of-week use POSIX OR.
Missing DST times advance to the first valid time; ambiguous folds fire once.
Downtime coalesces the latest due occurrence instead of replaying the backlog.
Reconciliation searches from the latest calendar time so a frequent schedule
does not allocate all missed occurrences after downtime.

<!-- relay-example: valid local-schedule -->
```yaml
on:
  schedule:
    - cron: '15 9 * * 1-5'
      timezone: America/New_York
jobs:
  check:
    steps: [{run: echo Scheduled check}]
```

`on.push` observes changed local branch/tag refs, without watching GitHub,
fetching remotes, or checking out another source. `branches`, `tags`, `paths`,
their `-ignore` forms, and ordered negative patterns filter changes.
Path filters apply to both branches and tags. The observed
ref/SHA must match the launch source; other deliveries block for review.

`on.repository_dispatch` accepts optional `types`. The authenticated loopback
API requires a nonempty `event_type` and an object `client_payload`. The
complete delivery payload must fit within 65,535 bytes; neither property
count nor event-name length has a separate hosted-service limit.
The `idempotency_key` must contain 1 to 200 characters. Normal owner
and CSRF requirements apply in both login modes.

`on.workflow_run` supports completed local runs, workflow name/key and branch
filters, and local `conclusions: [success, failure, cancelled]`. Follow-ups
reject cycles and chain at most three levels. No GitHub token is inherited.

## Anchors and diagnostics

Bounded anchors/aliases are supported. Duplicate keys, cycles, merge keys
(`<<`), custom tags, invalid field contexts, and unsupported keys fail with
field diagnostics. Bounds are 1 MiB YAML, 10,000 nodes, depth 50, 100 aliases,
21,000 expression characters, depth 50 expressions, and 10 MiB captured sources.

The browser preserves comments, anchors, aliases, expressions, field order,
and unsupported fields in drafts. Editing one alias detaches that occurrence
without changing its anchor. Invalid drafts recover across navigation/reload
but cannot be saved or launched. Server validation and leases remain
 authoritative.

<!-- relay-example: valid aliases -->
```yaml
jobs:
  main:
    steps:
      - &check
        run: echo Ready
      - *check
```

<!-- relay-example: invalid merge-key -->
```yaml
jobs:
  main:
    <<: {name: Check}
    steps: [{run: echo Ready}]
```

<!-- relay-example: invalid remote-action -->
```yaml
jobs:
  main:
    steps: [{uses: actions/checkout@v4}]
```

## Starter workflows

**Get started** and **Create workflow** offer six editable starters: Ask an
agent; Plan, approve, implement; Implement and test; Review my branch; Fix
until tests pass; and Write docs for a change. All use ordered local actions
and typed task inputs. Implement and test also offers a test-runner choice.
Writing starters commit at the job end. Existing owner files are never replaced.

The owner library imports/exports bounded JSON bundles containing `yaml`,
`sources`, and gallery `metadata` (`name`, `description`, `iconName`,
`categories`, `filePatterns`). Saving the current workflow captures local
reusable/action sources and project prompts. The library stays in installation
storage. Instantiate an editable copy in `.relay/`; normal launch gates apply.
`$default-branch` resolves from the recorded remote default, then configured
`init.defaultBranch`, then `main`, without a network call.

## Installation defaults

Owner settings supply exact provider order, model/effort defaults, named
commands, bounded recovery, and completion policy. Provider permissions remain
operational settings and never appear in public workflow YAML. Workflow
settings manage scoped variables and secret references.

Sources are portable. Databases, claims, credentials, logs, artifacts, caches,
private state, and worktrees stay in platform-specific installation storage.
See [projects and storage](projects-and-storage.md) and [HTTP API](http-api.md).
