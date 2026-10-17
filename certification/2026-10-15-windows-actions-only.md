# Windows Claude workflow check

Date: 2026-10-15. Windows 11 build 26300 x64; Python 3.14.7.
Claude Code 2.1.300 through ACP 0.91.0 selected `default` at
`6e23ab493cd9d1a45325be0fcf38b186e07cc6f5`. Eight artifact downloads
matched their hashes before and after cleanup; both worktrees were removed
and owned processes exited.

The [structured live record](2026-10-15-windows-actions-only.json) retains
the exact model, report and event hashes, versions, and cleanup results.

## Fresh live Claude check

At `6e23ab4`, Claude Code 2.1.300 through ACP adapter 0.91.0 completed a
production Actions workflow in a disposable Windows project. Fresh model
selection confirmed the literal advertised value `default`; it does not
identify Claude's concrete backend model. Effort and permission overrides
remained unset. Two exact diagnostic/file requests received one-use answers.

The command emitted Unicode stdout, stderr, intentional structured exit code
3, and a synthetic secret split across writes. Public tool events retained
the diagnostics and masked the secret. The agent wrote `PROVIDER-RETEST.md`;
Relay verified its label, retained its exact bytes, committed once at the
job boundary, and advanced the protected head. The 225-byte report has SHA-256
`aa05fa2ba3b07a2fc074d0a5f8cb2128f191257860a4aa5607d2cc31f7de47a1`.

All eight downloads matched their recorded hashes before and after worktree
cleanup. The launch checkout stayed clean and on its captured head. Provider
process identities cleared, the supervisor and its children stopped
cooperatively, and its ownership record disappeared.

An earlier diagnostic run timed out while the test helper waited to inspect
a command with an extra exit-code echo. Its record remains separate. The
successful retest required the exact diagnostic command; it did not change
the selected model or enable blanket approval. Both worktrees were removed
through Relay's confirmed cleanup API.
