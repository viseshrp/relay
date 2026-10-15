# Agent certification

Relay certifies an agent only after the exact adapter or binary completes an
authenticated model probe and an end-to-end run in a disposable Git worktree.
Command discovery, registry metadata, and source review are supporting evidence,
not a live certification.

## Latest five-provider pass

The latest pass ran on macOS 26.6.1 arm64 on 2026-10-03. The structured record
is in [`2026-10-03-macos-arm64.json`](2026-10-03-macos-arm64.json). Each successful
run selected a fresh advertised model value, wrote and committed exact UTF-8
bytes in a disposable worktree, preserved the declared artifact with its
SHA-256, advanced the protected head, cleared its process ID, and removed its
worktree through `clean_on_success`.

| Agent | Exact command version and model value | Result |
| --- | --- | --- |
| Codex | `codex-acp` 2.1.1; `gpt-6-luna` | Certified. ACP completed the prompt before SIGTERM stopped the adapter; the attempt stayed succeeded. |
| Claude Code | `claude-agent-acp` 0.85.1 and `claude` 2.1.288; `haiku` | Certified with one-use permission answers delivered through Relay's durable mailbox. |
| GitHub Copilot CLI | `copilot` 1.0.91; `auto` | Certified. A one-use permission answer traveled through Relay's durable mailbox to the live ACP request. |
| Cursor CLI | `cursor-agent` 2026.10.01-e373342; `default[]` | Certified with a one-use permission answer delivered through Relay's durable mailbox. |
| Antigravity | `agy` 1.2.16; `gemini-3.8-flash-low` | Certified with `auto_approve` and the native stdin stream. |

Copilot and Cursor advertised and confirmed the literal ACP values `auto` and
`default[]`, respectively. These values do not identify the concrete backend
models the providers chose. Antigravity proves native model-list membership
and an explicit `--model` argument rather than ACP configuration confirmation.

No certified ACP attempt required client-mediated file or terminal methods.
Codex and Claude probes advertised session deletion that SDK 0.12.1 cannot
perform; provider-owned probe history may remain. Retained ACP session IDs in
attempt records are diagnostic metadata, not resumable Relay sessions.

All five agents meet the certification bar below on this macOS arm64 host.
Claude and Cursor completed native CLI account sign-in before their successful
runs. The sanitized [Claude](2026-10-03-claude-sign-in.jpg) and
[Cursor](2026-10-03-cursor-sign-in.jpg) screenshots show the completed browser
handoffs. Live agent execution on Linux, live cancellation, model
drift, elicitation, provider timeout paths, and Antigravity's `respect_settings`
soft-deny notice remain unverified. Passing offline CI on those operating
systems does not certify a live provider.

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

## Windows dogfood and fix retest

On 2026-10-14, live Codex ACP 2.2.2 with exact model `gpt-6.1-sol` completed
a retained SuspendIt workflow on Windows. The
[initial run](2026-10-14-windows-suspendit.md) found four Relay defects. The
[fix retest](2026-10-14-windows-relay-fixes.md) verifies their fixes through
live execution, browser checks, an owner wait, and retained tool diagnostics.
The [full Python follow-up](2026-10-14-windows-python-suite.md) records the
fixture fix, real junction coverage, and a verified complete Python 3.14
Windows pass. Antigravity remains unverified on Windows.

The [2026-10-15 automated follow-up](2026-10-15-windows-end-to-end.md) records
the complete Windows browser and Python passes, portable test fixtures,
checklist focus restoration, and deep-path Git regression coverage.

The [optional review follow-up](2026-10-15-windows-optional-review.md) closes
S1 through S9 and records two further defects found during live testing.
The [Windows ACP record](2026-10-15-windows-acp.json) certifies Claude Code,
Copilot CLI, and Cursor CLI on the fixed Actions runtime. All three completed
fresh exact-model selection, one-use permission exchanges, retained reports,
job commits, browser output checks, and verified worktree cleanup. Copilot
returns its command exit code in public text; Claude and Cursor also return
structured exit fields. The final supervisor stopped cooperatively.

## Certification bar

A complete agent record must contain:

1. The exact binary or adapter version and target operating system.
2. An authenticated disposable session that reports model values.
3. Exact-model selection and confirmation from the resulting configuration.
4. An end-to-end attempt in an isolated worktree, including cleanup evidence.

These files are repository evidence only. The build content gate excludes the
entire `certification/` directory from source distributions and wheels.
