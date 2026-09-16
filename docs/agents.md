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
upgrade. SDK 0.12.1 still gates session-close routing behind its unstable
feature negotiation, so Relay enables that negotiation only to call a close
capability the agent advertised. The SDK exposes no supported session-delete
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
event limit is split into numbered UTF-8-safe parts. For example, one 70 KiB
message becomes three ordered `agent.message` events rather than one truncated
event. Agent stderr is retained as `agent.stderr` events.

Relay always services permission requests and form or URL elicitations through
the browser-backed durable mailbox. The request contains only the tool title,
offered option IDs, names, and kinds; provider-private request fields are not
persisted. The response goes only to the worker that owns the exact attempt and
session. A stale or duplicate answer cannot reach a later attempt. Cancel asks
ACP to cancel the session before Relay stops its process tree.

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
metadata. On 2026-09-16 UTC it reported Codex adapter 1.12.0, Claude adapter
0.78.0, GitHub Copilot CLI 1.0.83, and Cursor 2026.09.10. These observations are
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
agy -p <composed prompt> --output-format stream-json --model <exact value> --print-timeout <duration>
```

The `auto_approve` permission profile adds
`--dangerously-skip-permissions`; `respect_settings` does not. Auto-approval
allows every Antigravity tool and should be used only with a trusted prompt.
Headless mode cannot pause for mid-run permission or elicitation input.

Antigravity always has a print timeout. A node timeout such as `15m` becomes
`--print-timeout 15m`. With no node timeout, Relay uses Antigravity's documented
five-minute default and passes `--print-timeout 5m` explicitly.

Relay retains stdout and stderr in UTF-8-safe chunks before normalizing NDJSON,
using a bounded queue that applies pipe backpressure. JSON parsing holds at
most one 1 MiB line; a larger line is retained as raw output and then fails the
attempt as a protocol error. Cancellation and timeout drain bytes already read
before the attempt settles. Relay also inspects stream fields and stderr for
documented soft-deny signals. A target such as
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

| Agent | Local status on 2026-09-16 UTC | Certification status |
| --- | --- | --- |
| Codex | `codex-cli 0.145.0` present; `codex-acp` adapter absent | Blocked on registry adapter installation and live authenticated probe. |
| Claude Code | `claude` and ACP adapter absent | Blocked on binary and credentials. |
| GitHub Copilot CLI | CLI absent | Blocked on binary and credentials. |
| Cursor CLI | CLI absent | Blocked on binary and credentials. |
| Antigravity | `agy` absent | Blocked on binary and credentials. |

The registry endpoint and all five install links above returned HTTP 200 on
2026-09-16 UTC. The current registry document passed Relay's structural validation.
The ACP SDK pin, Codex and Claude adapter sources, and Antigravity's headless
documentation were reviewed for the commands, model selection, stream format,
permission behavior, and timeout described here. Missing live prerequisites
remain explicit gaps; Relay does not claim five-agent or cross-platform
certification from this machine. The sanitized local record and selected
registry fixture are under [`certification/`](../certification/README.md).
