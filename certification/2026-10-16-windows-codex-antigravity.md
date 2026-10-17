# Windows Codex and Antigravity checks

Date: 2026-10-16. Windows 11 build 26300 x64; Python 3.14.7.
Tested implementation: `dd752c651f183e20584ccba2a3b514e72a971991`.
Codex ACP 2.2.2 selected `gpt-6.1-sol`; Antigravity 1.3.6 selected
`gemini-3.8-flash-low`. All 13 artifact downloads matched their hashes;
both worktrees were removed and owned processes exited.

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

Antigravity executable SHA-256:

```text
b8155654c01e7dd45eb15232722f905872d62e4424307d4e0ded4ee2687d4249
```
