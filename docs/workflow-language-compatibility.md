# Workflow language compatibility

Relay implements a local subset of GitHub Actions YAML. It adopts the jobs,
steps, expression, input, matrix, output, reuse, and command-file contracts
where they fit a single-owner application. Execution uses local coding agents
and a serial cumulative Git workspace. This is a Relay execution dialect.

## Primary sources and review passes

The comparison used three passes through GitHub's own documentation:

1. Enumerate every workflow root, event, job, and step field in the
   [workflow syntax reference](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax).
   Classify existing Relay equivalents, missing local features, and platform
   infrastructure that has no Relay execution contract.
2. Cross-check semantics in the
   [expressions reference](https://docs.github.com/en/actions/reference/workflows-and-actions/expressions),
   [contexts reference](https://docs.github.com/en/actions/reference/workflows-and-actions/contexts),
   [workflow commands](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands),
   [action metadata](https://docs.github.com/en/actions/reference/workflows-and-actions/metadata-syntax),
   and [reuse documentation](https://docs.github.com/en/actions/how-tos/reuse-automations/reuse-workflows).
   Check coercion, field availability, raw outcomes, secret propagation,
   file consumption, cleanup hooks, and nested limits.
3. Reconcile the first two passes against Relay's parser, durable execution,
   source capture, Git admission, persistence, owner controls, API, editor,
   and tests. Resolve product differences explicitly, then map each accepted
   addition to implementation and validation.

The pinned grammar and expression fixture source is GitHub's MIT-licensed
[actions/languageservices revision](https://github.com/actions/languageservices/tree/4043eda158e16579cc5fb1b0b07a4bce2a76f0b5).
Its license and provenance accompany `relay/workflows/actions/upstream-schema.json`
and `tests/fixtures/actions/expressions`. The browser parser uses the matching
exact `@actions/expressions` package version, `0.3.61`. The Python interpreter
and browser oracle consume the upstream expression fixtures independently.
Local additions such as `case`, `cache-mode`, time zones, queue policy, and
completion-conclusion filters have separate contracts and regression checks.

GitHub documentation describes a broader hosted platform. The pinned grammar
is supplemented by Relay's explicit support manifest, rather than treating
an accepted upstream key as proof that Relay can execute it.

## Accepted feature map

| Feature | Owning implementation | Validation subject |
| --- | --- | --- |
| Jobs and ordered steps, stable IDs, names and run-name | `actions/compiler.py`, `nodes/actions.py` | Shared edits, final job commit, display names |
| Expressions, coercion, missing properties and case-insensitive equality | `actions/expressions.py` | Upstream fixture corpus and browser oracle |
| Functions, object filters, status predicates and hashFiles | `expressions.py`, `patterns.py` | Functions, traversal bounds, status conditions |
| Field-specific expression contexts | `actions/language.py` | Rejected secret/step contexts in unavailable fields |
| Anchors, aliases and duplicate/tag/merge diagnostics | `language.py`, `frontend/src/actions-workflow.ts` | Bounded parse and comment-preserving edits |
| Script strings/blocks, shells, workdirs and defaults | `action_files.py`, `nodes/actions.py` | Explicit argv, owned processes and timeout |
| Shared workspace and cumulative job checkpoints | `runner.py`, `actions_repository.py` | Accepted A/B commits and rejected-job retention |
| Raw outcomes, conclusions, tolerance and failure follow-ups | `repositories.py`, `nodes/actions.py` | Tolerated failures and unrelated-job continuation |
| Persisted job/step timeouts | `actions_repository.py` | Deadline inheritance and suspension |
| Serial static/dynamic matrix, include/exclude and fail-fast | `language.py`, `nodes/actions.py` | Frozen manifests and serial variant outputs |
| Scoped concurrency with single/FIFO/cancel policies | `actions_automation.py`, `ActionsQueue` | No lease held by queued owners or nested self-block |
| Local reusable workflows with typed inputs/outputs | `compiler.py`, `nodes/actions.py` | Frozen transitive calls and limits |
| Explicit/inherited scoped secrets and matrix call outputs | `actions_bindings.py`, `nodes/actions.py` | Contract enforcement and environment precedence |
| Composite actions with frozen files and required inputs | `metadata.py`, `nodes/actions.py` | Owner edits cannot affect captured action bytes |
| Installed Node 20/24 actions with main/post hooks | `metadata.py`, `nodes/actions.py` | Exact major, state isolation and bounded cleanup |
| Versioned agent and argument-vector command adapters | `actions/builtins.py`, `nodes/actions.py` | Exact routes, prompts and command bounds |
| Human waits, loops, report and input validation | `nodes/actions.py`, `actions_repository.py` | Current-attempt answers and retained report bytes |
| Bounded repair and confirmed-usage-reset recovery | `repositories.py`, `actions_repository.py` | Durable budgets and separate repair instructions |
| Library metadata, import/export and default-branch copy | `workflows/library.py` | Owner files preserved and sources validated |
| Six jobs/steps starters | `workflows/starters/` | Source validation and deterministic full execution |
| Installation/project/environment variables | `actions_bindings.py`, `WorkflowBinding` | Frozen values and scope precedence |
| Environment/native credential references and masking | `native_credentials.py`, `masking.py` | Explicit OS backend, no database secret values |
| Environment approval, timers, branch filters and URL | `actions_repository.py`, `WorkflowEnvironment` | Approval before secret resolution and stale rejection |
| OUTPUT/ENV/PATH/STATE files | `action_files.py` | UTF-8, multiline, protected names and consume-once |
| String public outputs and typed private reports | `nodes/actions.py`, `actions_repository.py` | UTF-16 budgets and secret-bearing export rejection |
| Named hashed artifacts, downloads and optional expiry | `action_products.py`, `actions_products.py` | Integrity, same-project access and required evidence |
| File/OCI artifact subjects and cumulative LIST | `action_files.py` | Digests, subject bounds and conflicts |
| Immutable project caches, modes, prefix match and LRU | `action_products.py`, `actions_products.py` | Capability intersection and owned restore paths |
| Summaries, annotations, groups, debug and log commands | `action_commands.py`, `ActionsRunProducts.tsx` | Masking, stop-commands and agent prose isolation |
| Typed manual choice/environment launch inputs | `language.py`, `LaunchPanel.tsx` | Type/default/unknown input checks |
| POSIX schedules, IANA zones, DST and latest coalescing | `triggers.py`, `actions_automation.py` | Gap/fold behavior and deduplicated delivery |
| Observed local ref filters and bounded repository_dispatch | `triggers.py`, `actions_automation.py` | Activation, changed-source blocking and payload bounds |
| Completed local workflow_run with filters and chain limits | `actions_automation.py` | Completion cursor, cycles and bounded chaining |

Paths without a prefix above are in `relay/workflows/actions/`,
`relay/execution/`, or `relay/web/` as named in the repository code map.
Focused Python contracts live in `tests/test_actions_*.py`; browser contracts
live in `frontend/e2e/` and `frontend/scripts/`. Tests cover the current public
save/launch contract and durable execution.

## Product decisions

The public schema is replaced without a version opt-in because Relay is
unreleased. Historical launch snapshots retain a legacy semantics revision and
frozen definition. Old editable sources and drafts may be replaced or
discarded. The browser does not offer a legacy conversion flow.

Jobs and all nested/matrix work run serially. Agent edits and tests share the
primary worktree. Code changes require a clean descendant commit at job end;
a clean no-op is valid. Failed work is retained before continuation from the
last accepted checkpoint. No automatic merge is introduced; the existing
explicit completion policy remains the only integration path.

Local `relay/...@v1` actions replace GitHub platform actions. Reusable sources
stay under `.relay/workflows`, while local action assets stay under `.relay`.
Routes, prompts, typed inputs, sources, variables, and environment policies
freeze at launch. Credential values are resolved through frozen references
only after the relevant gate. Workflow YAML does not grant permissions.

Automatic triggers require owner activation, including authorization for
writing jobs. Ref triggers observe local Git state and never fetch or check
out another branch. Dispatch APIs retain loopback, owner, host, and CSRF rules.
Schedules and completion events deduplicate durable delivery identities.

## Excluded platform features

GitHub-hosted runners, remote workers, containers, service containers,
Docker actions, remote repository actions, GitHub app/token permission scopes,
OIDC federation, hosted environments/deployment APIs, remote artifact
attestations, remote repository event subscriptions, release/package actions,
and automatic agent/runtime installation have no local execution contract.
They fail validation rather than implying partial support.

Parallel jobs/matrix execution, background jobs/services, and JavaScript pre
hooks are deferred. They require new ownership, workspace, cancellation,
cleanup, and recovery contracts. The current serial lease is not presented as
parallel execution. Provider permission settings remain available through
owner administration, without a YAML permission field.

## Implementation sequence

1. Pin grammar, fixtures, license and browser oracle; introduce strict
   validation, source-aware diagnostics, expression contexts and execution IR.
2. Persist serial jobs/steps, matrix manifests, lease admission, raw/effective
   outcomes, deadline inheritance, accepted checkpoints and recovery state.
3. Add owned scripts, frozen local/reusable actions, built-in adapters and
   bounded already-registered cleanup.
4. Add scoped bindings, native references, masking and exact-attempt
   environment gates across persistence, owner APIs and browser settings.
5. Add file commands, string outputs, summaries, artifact subjects, named
   products, immutable caches, integrity checks and optional expiry.
6. Add activated local schedules/ref/dispatch/completion events with cursors,
   deduplication, blocked deliveries, chain bounds and named queues.
7. Replace browser authoring with jobs/steps, preserve source round trips,
   add monitoring/settings/library controls, convert starter sources, and run
   the Python, browser, documentation and distribution gates.

Each phase extends the same durable execution and preservation contracts.
Offline provider tests do not certify installed accounts. Native-store tests
must not access an owner's credentials. A local interpreter pass does not
establish other operating systems or the supported Python matrix.

## Implementation and validation status

All seven implementation phases and all 33 accepted feature groups above are
implemented. The validation record on 2026-10-08 is:

| Check | Result |
| --- | --- |
| Full Python suite on macOS, Python 3.10 through 3.14 | 2,413 passed and one platform-specific skip on each interpreter |
| Latest effort/default and job-monitoring changes on all five interpreters | 288 affected regression tests passed on each interpreter |
| Browser suite with login and without login | 184 and four tests passed, respectively |
| Browser expression oracle and asset-publication tests | 1,019 passed, five upstream-declared skips, zero failures |
| Quality, licenses, documentation and workflow examples | Passed |
| Wheel and source-distribution content checks | Passed |
| Fresh wheel startup with neither Node nor npm on PATH | Passed; all 661 packaged static files matched their hashes |

Execution checks use disposable repositories and storage with deterministic
provider processes. Installed Node 20 and 24 exercised local JavaScript
actions. Native credential tests use isolated substitutes and do not access
owner credentials. The skipped Python test requires Windows directory
junctions; these results do not certify Linux, Windows, or live providers.

The running owner's server was restarted with the verified build and its
existing storage and login choice. Live API and browser checks passed, and
database records, settings, retained artifact hashes, and the existing paused
run were preserved. These health checks did not launch or resume owner work.
