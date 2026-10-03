# Agent certification

Relay certifies an agent only after the exact adapter or binary completes an
authenticated model probe and an end-to-end run in a disposable Git worktree.
Command discovery, registry metadata, and source review are supporting evidence,
not a live certification.

## Latest local pass

The latest pass ran on macOS 26.6.1 arm64 on 2026-10-03. The structured record
is in [`2026-10-03-macos-arm64.json`](2026-10-03-macos-arm64.json). Each successful
run selected a fresh advertised model value, wrote and committed exact UTF-8
bytes in a disposable worktree, preserved the declared artifact with its
SHA-256, advanced the protected head, cleared its process ID, and removed its
worktree through `clean_on_success`.

| Agent | Exact command version and model value | Result |
| --- | --- | --- |
| Codex | `codex-acp` 2.1.1; `gpt-6-luna` | Certified. ACP completed the prompt before SIGTERM stopped the adapter; the attempt stayed succeeded. |
| Claude Code | `claude-agent-acp` 0.85.1 and `claude` 2.1.288; `haiku` | Model selection succeeded, but the real writer attempt failed with `agent_auth_error`. |
| GitHub Copilot CLI | `copilot` 1.0.91; `auto` | Certified. A one-use permission answer traveled through Relay's durable mailbox to the live ACP request. |
| Cursor CLI | `cursor-agent` 2026.10.01-e373342 | Fresh model preflight failed with `agent_auth_error`; no run was created. |
| Antigravity | `agy` 1.2.16; `gemini-3.8-flash-low` | Certified with `auto_approve` and the native stdin stream. |

Copilot advertised and confirmed the literal ACP value `auto`. That proves
Relay preserved the selected value; it does not identify the concrete backend
model Copilot chose. Antigravity proves native model-list membership and an
explicit `--model` argument rather than ACP configuration confirmation.

No certified ACP attempt required client-mediated file or terminal methods.
Codex and Claude probes advertised session deletion that SDK 0.12.1 cannot
perform; provider-owned probe history may remain. Retained ACP session IDs in
attempt records are diagnostic metadata, not resumable Relay sessions.

Claude and Cursor still need their own account sign-in. The five-agent
Definition of Done remains unmet. Live agent execution on Linux and Windows,
live cancellation, model drift, elicitation, provider timeout paths, and
Antigravity's `respect_settings` soft-deny notice remain unverified. Passing
offline CI on those operating systems does not certify a live provider.

The current registry fixture is
[`fixtures/registry-2026-10-03.json`](fixtures/registry-2026-10-03.json). Relay
fetched and validated it through its registry client. The
[2026-09-16 record](2026-09-16-macos-arm64.json) and its fixture remain as
historical evidence of the earlier missing-command blockers.

## Browser smoke run

Google Chrome completed a three-node command, human-wait, and command workflow
on 2026-10-03. The owner answered the wait in the browser, the next command's
output arrived without a reload, and the monitor showed `succeeded` with
`SSE complete`. Refreshing history showed the same terminal status. The
[screenshot](2026-10-03-browser-smoke.jpg) and the `browser_smoke` entry in the
structured record capture that run. Ctrl+C stopped the supervisor cleanly.

## Certification bar

A complete agent record must contain:

1. The exact binary or adapter version and target operating system.
2. An authenticated disposable session that reports model values.
3. Exact-model selection and confirmation from the resulting configuration.
4. An end-to-end attempt in an isolated worktree, including cleanup evidence.

These files are repository evidence only. The build content gate excludes the
entire `certification/` directory from source distributions and wheels.
