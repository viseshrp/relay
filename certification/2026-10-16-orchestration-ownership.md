# Orchestration ownership audit and Windows validation

Relay owns declared pipeline execution, workspace isolation, durable state,
owner controls, and retained evidence. Providers own their tools, permissions,
authentication, available models, and execution outcomes.

This audit covers PR [#23](https://github.com/viseshrp/relay/pull/23), from
`391ca00cee606e78ce874d9fbd3d2e464d4677fd` through the initial head
`39c736faee6b1848b4e2a7fa4ba98fd68ba79551`. The tested implementation is
`dd752c651f183e20584ccba2a3b514e72a971991`. Subsequent edits add this evidence
and clarify documentation; runtime hashes are in the
[structured record](2026-10-16-orchestration-ownership.json).

## Scope and disposition

The structured record names all 290 initial paths, their original Git change,
their disposition, and their ownership reason. It also names all 34
implementation follow-up paths and the documentation follow-up. Every changed
runtime path was traced through its relevant transport, execution, persistence,
API, and browser callers. A file's audit disposition does not imply that every
line ran during a test.

| Initial PR area | Paths | Disposition |
| --- | ---: | --- |
| Python runtime | 67 | Retain orchestration and transport duties; narrow provider-specific logic. |
| Browser runtime | 46 | Retain authoring, coherent monitoring, and exact owner controls. |
| Python tests and fixtures | 56 | Retain deterministic current workflow coverage. |
| Browser tests and captures | 39 | Retain current UI checks; replace inferred-denial assertions. |
| Visual evidence | 44 | Retain reviewed platform-specific bytes. |
| Certification records | 16 | Retain dated factual evidence, excluded from distributions. |
| Documentation | 17 | Describe current contracts and ownership. |
| Build and CI | 5 | Retain supported-platform gates and completeness checks. |

Deleted executors, UI fields, and their obsolete tests stay deleted. Existing
migration ordering and owner rows remain intact. No additional execution model,
compatibility promise, provider installer, or provider authentication flow was
added.

## Implemented boundaries

1. Native Antigravity terminal status and process exit determine its result.
   Tool notices and stderr prose remain diagnostics. Relay no longer scans
   denial phrases, interprets write targets, or overrides provider success from
   those messages. A missing required report fails the declared output contract.
2. Valid provider execution failures use `agent_execution_error`; malformed
   exchanges use `agent_protocol_error`. Neither schedules automatic repair.
   ACP refusal, token limits, and provider cancellation remain provider failures.
   Raw `provider_stop_reason` is separate from typed Relay cancellation,
   interruption, and timeout state in attempt events, monitor/API payloads, and
   browser types. Explicit workflow loops, owner retries, and structured
   confirmed usage-reset schedules keep their own admission rules.
3. Relay enforces configured step and inherited deadlines. Antigravity receives
   `--print-timeout` only for such a deadline. Copied provider defaults and
   duration-based timeout inference were removed. A provider's final success
   message cannot disable Relay's configured deadline while its process hangs.
4. Windows storage grants preserve inherited access for the directory owner.
   New storage no longer grants broad account or provider sandbox access. Existing
   unrelated ACL entries remain unchanged; Relay has no provenance to revoke
   them. Native tests verify owner inheritance, idempotence, and failure cleanup.
5. An Actions report is resolved once into a typed selector, sent through ACP or
   the native prompt, and used for validation and rejected-report preservation.
   Label, JSON, YAML, optional existence, and full selectors share that contract.
   Captured prompt/source bytes remain unchanged. Relay adds workspace facts and
   declared I/O metadata; unsolicited report provenance and phase advice were
   removed.

Streaming masks, output bounds, exact model proof, process ownership, durable
mailboxes, and Git evidence preservation remain Relay duties. The Windows UTF-8
script fix, workflow inventory refresh, display-name event subscription, and
portable Git path/commit handling remain because they correct Relay's own
orchestration and UI behavior.

## Native Windows automated checks

The complete `uv run tox -e py314` run collected and verified 2,850 distinct
tests at the tested implementation: **2818 passed, 32 skipped, zero
failures**. The completeness gate compared every collected node ID and checkout
SHA with both JUnit lanes, rejecting omissions, duplicates, unexplained skips,
and worker restarts. Exact skip reasons and report hashes are in the JSON record.

Python 3.14.7 ran on native Windows with three parallel workers. Both JavaScript
action runtimes were present: Node 20.20.2 and 24.12.0. Git Bash and PowerShell
were resolved to absolute executable paths and exercised before the final run.

The first full invocation selected a nonfunctional Windows WSL Bash launcher
and failed 20 Bash-dependent tests. All 20 passed after correcting PATH; the
complete suite was then repeated. This setup correction changed no product code.

Focused transport, report, deadline, provider-result, and ACL checks passed.
Browser validation passed seven existing recovery/problem cases, both new
native outcome cases, and all four no-login cases. All 16 monitor unit tests
passed. The frontend build/oracle checks passed 1,036 cases with five declared
skips. Fresh browser assets were built into isolated storage and their index
hash is recorded.

The lockfile check, all tracked-file pre-commit hooks, Windows/Linux/Darwin type
checks, frontend lint/format/type/build checks, documentation links, transition
documentation, workflow examples, and whitespace checks passed. Full platform
and browser matrix results are recorded on the PR against its final CI checkout.

## Bounded live Windows checks

Both runs used a disposable Git repository, isolated Relay storage, existing
provider authentication, exact models freshly proved by Relay, unset effort and
permission overrides, disabled automatic recovery, and a three-minute step
deadline. No model, provider, permission, authentication, or retry fallback was
used. The repository's launch checkout stayed clean and at its original head.

| Provider | Exact version and model | Result |
| --- | --- | --- |
| Codex ACP | 2.2.2; `gpt-6.1-sol` | Succeeded once. The provider wrote the required report and the following Python step verified its exact bytes. |
| Antigravity | 1.3.6; `gemini-3.8-flash-low` | Returned `SUCCESS` and exit 0 without the required report. Relay failed with `output_validation_error` and preserved the provider reason. |

The Codex report contains exactly `Ready: YES` followed by LF: 11 bytes,
SHA-256
`7911e42bdf5283b204d484841af9e7e560fd875592887353761297573d9a6329`.
Its ACP stop reason was `end_turn`; the adapter's post-turn cooperative shutdown
exit is recorded separately. Antigravity's run verifies enforcement of a
missing declared contract; it does not certify successful native task completion
under the provider's current defaults.

Neither run created an automatic repair or usage retry. All 13 downloaded
artifacts matched their retained sizes and hashes. Both attempts cleared their
process IDs. Confirmed Relay cleanup removed both worktrees after preserving
evidence. Supervisor shutdown verified creation identities, stopped its owned
processes, and cleared the ownership record.

Raw provider logs and unredacted captures remain outside the repository.
Linux Codex sign-in remains deferred at the owner's request. Existing dated
provider records keep their original scope; this audit makes no new Linux live
certification claim. The three owner review documents remain byte-for-byte
unchanged, with their hashes recorded in JSON.

The PR remains open for owner review, with auto-merge disabled.
