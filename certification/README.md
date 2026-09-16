# Agent certification

Relay certifies an agent only after the exact adapter or binary completes an
authenticated model probe and an end-to-end run in a disposable Git worktree.
Command discovery, registry metadata, and source review are supporting evidence,
not a live certification.

## Latest local pass

The latest pass ran on macOS 26.6.1 arm64 at 2026-09-16T03:56:13Z. The structured
record is in
[`2026-09-16-macos-arm64.json`](2026-09-16-macos-arm64.json).

| Agent | Local command evidence | Result |
| --- | --- | --- |
| Codex | `codex-cli 0.145.0` present; `codex-acp` absent | Blocked before authentication, model probing, and worktree execution. |
| Claude Code | `claude` and `claude-agent-acp` absent | Blocked before authentication, model probing, and worktree execution. |
| GitHub Copilot CLI | `copilot` absent | Blocked before authentication, model probing, and worktree execution. |
| Cursor CLI | `cursor-agent` absent | Blocked before authentication, model probing, and worktree execution. |
| Antigravity | `agy` absent | Blocked before authentication, model probing, and worktree execution. |

`relay doctor` returned exit code 6 because none of the five exact execution
commands was ready. Its Git, database, packaged-asset, and ACP registry checks
passed. Relay did not test credentials after a required command was missing.

The current registry fixture is
[`fixtures/registry-2026-09-16.json`](fixtures/registry-2026-09-16.json). The
registry endpoint and all five official install links returned HTTP 200 during
the pass. No agent is claimed as live-certified on this host.

## Certification bar

A complete agent record must contain:

1. The exact binary or adapter version and target operating system.
2. An authenticated disposable session that reports model values.
3. Exact-model selection and confirmation from the resulting configuration.
4. An end-to-end attempt in an isolated worktree, including cleanup evidence.

These files are repository evidence only. The build content gate excludes the
entire `certification/` directory from source distributions and wheels.
