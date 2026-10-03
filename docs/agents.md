# Coding agents

Relay Phase 1 supports five agent families: Codex, Claude Code, GitHub Copilot
CLI, and Cursor CLI through ACP; Antigravity through its native headless
interface. Relay discovers existing commands. It does not install an agent,
create a vendor account, or store provider credentials.

## Exact-model routing

A workflow `model` is an exact, case-sensitive value advertised by the selected
agent. It is not a Relay alias. Before a run is created, Relay opens one
disposable session per candidate agent, reads that session's model values, sets
the requested value, and requires the complete returned configuration to name
the same current value. A cached observation may populate the launch form but
never authorizes a run.

For example, requested value `gpt-5.3-codex` matches only an option whose value
is exactly `gpt-5.3-codex`; a display label such as `GPT 5.3 Codex` and a value
such as `gpt-5.3-codex-high` do not match. The first candidate in the node,
workflow, then owner preference order that proves the value is frozen into the
node route. Relay does not fall back to a different model. The node's fresh ACP
session repeats the selection proof. If a later `config_option_update` reports
a different value, Relay cancels and fails that attempt.

An explicit `permission_profile` must be supported by the candidate agent at
launch preflight. Relay reports permission and route failures together before
running any node. Registry installation metadata is advisory; a registry fetch
failure does not prevent installed agents from proving their routes.

ACP authentication failures use the protocol's `auth_required` code. An
adapter disconnect or early exit is a protocol failure; words such as `auth`
or `config` in unrelated diagnostics do not decide the error category. Probe
reports retain each failure's code and message separately.

The attempt deadline, cancellation mailbox, and heartbeat cover initialization,
model selection, prompt execution, and provider shutdown as one lifecycle.

Antigravity is not an ACP agent in Relay. Its preflight requires exact
membership in a fresh `agy models` result. Execution passes the same value with
`--model` and rejects a different model reported by the stream, but the native
interface has no ACP configuration-change notification.

## ACP boundary

Relay pins `agent-client-protocol` 0.12.1 and protocol version 1. It initializes
each adapter over stdio, opens a fresh session in the assigned Git worktree
without MCP servers, selects the model, sends the prompt, closes the session
when supported, closes stdio, and stops the process tree within a bounded
grace. The SDK is pre-1.0; its pin and behavior must be re-certified before an
upgrade. SDK 0.12.1 gates incoming `elicitation/create` on
`use_unstable_protocol=True`, which Relay enables for browser-backed
elicitations. The outgoing `close_session` call does not require that flag.
The SDK exposes no supported session-delete
client method; Relay reports a cleanup warning when an agent advertises delete
and the disposable session may remain.

Static prompt files are separate ACP text blocks in declared order. Inputs,
run metadata, and upstream outputs are three later JSON blocks. For example,
prompt bytes `Review this file.\n` remain unchanged in their block, while input
`{"target":"api"}` appears in a separate block headed `Relay inputs (JSON)`.
Relay never appends an earlier conversation transcript.

ACP message, thought, tool-call, tool-result, and plan updates become Relay
events. Content explicitly marked for an audience that excludes `user`, or
marked private in ACP metadata, is dropped. A visible string larger than the
event limit is split into numbered UTF-8-safe parts sized after JSON escaping.
For example, a 70 KiB plain-text message becomes three ordered `agent.message`
events; quotes, backslashes, and control characters can require more parts.
Each provider payload stays within 32 KiB, reserving space for Relay metadata
and SSE framing. ACP stderr drains as soon as the process starts, including
initialization, model selection, and shutdown. Attempts retain it as
`agent.stderr` events; disposable model probes discard it.

Relay always services permission requests and form or URL elicitations through
the browser-backed durable mailbox. The request contains only the tool title,
offered option IDs, names, and kinds; provider-private request fields are not
persisted. The response goes only to the worker that owns the exact attempt and
session. A stale or duplicate answer cannot reach a later attempt. Cancel asks
ACP to cancel the session before Relay stops its process tree. Relay signals
the isolated process group, waits up to ten seconds, then forces the tree to
stop. On Windows it uses a console break followed by `taskkill /T /F` when
needed; on Linux it signals the process group with `SIGTERM` then `SIGKILL`.
The final exit wait is bounded. Windows behavior remains unverified until a
Windows certification run.

The Phase 1 profiles advertise no client-mediated file or terminal methods:

| Agent | Model option ID | Client file methods | Client terminal methods |
| --- | --- | --- | --- |
| Codex | `model` | none | none |
| Claude Code | `model` | none | none |
| GitHub Copilot CLI | `model` | none | none |
| Cursor CLI | `model` | none | none |

Agents operate directly in the assigned worktree. Relay advertises ACP file or
terminal methods only after that exact requirement is certified for a profile;
an unadvertised request fails rather than acquiring wider access.

## Install and authentication ownership

The official ACP registry supplies adapter package versions and installation
metadata. On 2026-10-03 UTC it reported Codex adapter 2.1.1, Claude adapter
0.85.1, GitHub Copilot CLI 1.0.91, and Cursor 2026.10.01. These observations are
dated, not permanent pins. `relay doctor` refreshes registry metadata with a
bounded request, displays installation guidance, and never runs a package
manager.

| Agent | Registry or native install guidance | Authentication |
| --- | --- | --- |
| Codex | [`@agentclientprotocol/codex-acp`](https://github.com/agentclientprotocol/codex-acp) | Authenticate Codex before starting the adapter. |
| Claude Code | [`@agentclientprotocol/claude-agent-acp`](https://github.com/agentclientprotocol/claude-agent-acp) | Authenticate Claude Code directly. |
| GitHub Copilot CLI | [Install Copilot CLI](https://docs.github.com/en/copilot/how-tos/set-up/install-copilot-cli) | Run the Copilot login flow directly. |
| Cursor CLI | [Cursor ACP setup](https://cursor.com/docs/cli/acp) | Run `cursor-agent login` directly. |
| Antigravity | [Antigravity CLI installation](https://antigravity.google/docs/cli/install/) | Authenticate once in `agy` or configure its supported API key. |

Adapter commands remain argument vectors. Registry package text such as
`@agentclientprotocol/codex-acp@1.12.0` is displayed verbatim; Relay does not
split, shell-expand, or execute it until a later explicit browser installation
confirmation. A stale validated registry cache may support discovery when a
refresh fails, but Relay displays its age and warning.

Agent and command processes inherit the full Relay worker environment. Relay
has no secret vault, environment allowlist, or masking layer. Prompts, model
output, tool details, stderr, permission answers, Git diffs, and artifacts can
contain sensitive data and remain in local Relay storage until the owner
deletes the run. Provider authentication data stays in the provider's own CLI
or operating-system credential store. Relay emits no product telemetry.

## Antigravity differences

Relay executes Antigravity as:

```text
agy --input-format stream-json --output-format stream-json
    --model <exact value> --print-timeout <duration>
```

Relay sends one UTF-8 JSON line to stdin and closes the pipe:

```json
{"event":"user","message":{"content":"Review.\nNext."}}
```

The content contains the ordered prompt files followed by the three Relay JSON
sections. JSON escaping preserves newlines, quotes and Unicode without passing
the prompt through a Windows batch command line. The
[headless stdin contract](https://antigravity.google/docs/cli/headless/#stream-prompts-from-stdin)
allows EOF immediately after the final prompt; Antigravity completes that turn,
emits its result and exits. Relay drains stdout and stderr while writing stdin
so startup diagnostics cannot block prompt delivery.

The `auto_approve` permission profile adds
`--dangerously-skip-permissions`; `respect_settings` does not. Auto-approval
allows every Antigravity tool and should be used only with a trusted prompt.
Headless mode cannot pause for mid-run permission or elicitation input.

Antigravity always has a print timeout. A node timeout such as `15m` becomes
`--print-timeout 15m`. With no node timeout, Relay uses Antigravity's documented
five-minute default and passes `--print-timeout 5m` explicitly.
Relay also enforces that ceiling with a monotonic deadline from process
startup, including when the node has no declared timeout. Expiry reports
`node_timeout` with stop reason `timeout`. A received `SUCCESS` result is
not reclassified as a print timeout while buffered output drains. Relay does
not infer timeout from the free-text `error` field. An `ERROR` result whose
documented numeric `duration_seconds` reaches the print ceiling also reports
a timeout. The headless documentation provides no separate timeout code.
Live timeout behavior remains unverified.

The disposable `agy models` probe has a 15-second response limit and runs in
its own process group. Relay stops that group before reporting a model-list
timeout.

The complete composed prompt must fit in 32 KiB of UTF-8. On Windows the
command must also fit the 32,767 UTF-16-unit process limit, including its final
NUL, or the smaller 8,191-character limit when the executable is a `.cmd` or
`.bat` shim. Relay checks the quoted command and wrapper allowance before
starting it. Oversized input raises `node_execution_error` with guidance to
reduce prompt files, inputs, or upstream output. The command-line limit applies
only to the executable, adapter arguments, model and flags; the prompt travels
through stdin. An oversized command reports the same code with guidance to
shorten its arguments or model value.

Relay retains stdout and stderr in UTF-8-safe chunks before normalizing NDJSON,
using a bounded queue that applies pipe backpressure. JSON parsing holds at
most one 1 MiB line; a larger line is retained as raw output and then fails the
attempt as a protocol error. Cancellation and timeout drain bytes already read
before the attempt settles. Relay detects soft denies only in complete stderr
tool notices, as described by the headless documentation. The exact notice
format remains unverified until live certification. A target such as
`write_file(src/report.md)` becomes worktree-relative `src/report.md`; a path
outside the worktree is ignored by the write-target rule. A writing attempt
fails with `soft_denied` when a denied target covers a required artifact, or
when at least one worktree-targeting write was denied and the attempt produced
no commit. A read-only node records but ignores these denies.

## Certification evidence

Certification requires the exact binary or adapter, its authenticated account,
the target operating system, a disposable model probe, and an end-to-end
worktree run. Source review and command discovery do not substitute for that
evidence.

| Agent | Exact version and model on 2026-10-03 UTC | Certification status on macOS arm64 |
| --- | --- | --- |
| Codex | `codex-acp` 2.1.1; `gpt-6-luna` | Passed an authenticated writer workflow. |
| Claude Code | `claude-agent-acp` 0.85.1 and `claude` 2.1.288; `haiku` | Model selection passed; the writer attempt failed with `agent_auth_error`. |
| GitHub Copilot CLI | `copilot` 1.0.91; `auto` | Passed a writer workflow with a mailbox-delivered permission answer. |
| Cursor CLI | `cursor-agent` 2026.10.01-e373342 | Fresh model preflight failed with `agent_auth_error`. |
| Antigravity | `agy` 1.2.16; `gemini-3.8-flash-low` | Passed a native stdin writer workflow with `auto_approve`. |

The successful runs verified the writer's committed bytes, declared artifact
hash, protected head, process cleanup, and successful worktree removal. No live
ACP attempt required client-mediated file or terminal methods. Copilot's
literal selector value `auto` was advertised and confirmed; its concrete
backend model was not identified.

Claude's model menu is available without authentication, so model selection
alone does not certify its account. Claude and Cursor await their own CLI
sign-in. Live provider behavior on Linux and Windows, cancellation, model
drift, elicitation, timeouts, and Antigravity soft denies remain unverified.
The five-agent Definition of Done remains unmet. The sanitized results and
fresh validated registry fixture are under
[`certification/`](../certification/README.md).
