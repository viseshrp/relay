# Windows dogfood test with SuspendIt

Date: 2026-10-14. Status: initial run completed.

R1-R4 were subsequently fixed and retested. See the
[Relay fix report](2026-10-14-windows-relay-fixes.md). The account below records
the initial run before those fixes.

## Scope and setup

Exercise Relay's browser authoring, exact-model launch, agent execution,
command steps, monitoring, and retained Git work using the sibling SuspendIt
repository. Build Windows renderer-memory measurement so its existing four
memory-release browser regressions can run on Windows.

- Windows 11 Home, version 10.0.26300, x64.
- Relay source: `391ca00cee606e78ce874d9fbd3d2e464d4677fd`.
- SuspendIt launch source: `982657ffbf4168b8509a0fe99f83cbcf7634b747`.
- Python 3.14.7; Node 24.12.0; pnpm 10.28.1.
- Codex ACP 2.2.2, installed under the test's temporary directory.
- Fresh model probe advertises `gpt-6.1-sol`; workflow selects that exact value.
- Relay runs at `http://127.0.0.1:7845` with explicit no-login mode and
  isolated platformdirs storage under `%TEMP%/relay-windows-20261014/storage`.
- Existing owner credentials, normal Relay storage, and personal Chrome tabs
  are outside the test. Extension tests use their own temporary profiles.

## Checks completed

- Relay locked Python environment installed; frontend build passed.
- `relay doctor --json` passed core checks and the Codex model probe.
- SuspendIt locked dependency installation and baseline `pnpm quality` passed.
- Chrome browser opened Relay, dismissed onboarding, selected SuspendIt, and
  created a copy of the Implement and test starter.

## Findings

### R1: step names remain stale until a state refresh

Priority: P2. Confirmed in the live browser.

The saved agent step is named `Add Windows renderer memory checks`. After
launch, the expanded job shows `1. Implement` for more than two minutes.
`GET /api/runs/{id}` and `/monitor` already return the full `display_name`.
The name updates in the browser immediately after the Pause control changes
run state. Output continued during that interval; the state cursor stayed 16.

Expected: the running step shows its resolved name without an owner action.
Check whether resolving a display name advances a state event/cursor.

### R2: Codex command output is missing from retained tool details

Priority: P2. Confirmed with Codex ACP 2.2.2; attribution needs follow-up.

The first failed shell commands appear as Failed in the browser, but their
expanded details contain the command and status with no failure reason.
Completed reads likewise expose a terminal ID rather than their output.
The API retains thousands of `agent.tool_call` events with `summary: "{}"`.
For example, events 201 through 400 all have that empty summary for the same
call. Failed result events 779, 986, 1183, and 1198 retain only a failed status.

Expected: an owner can inspect command output and the reason for failure.
Check adapter terminal-output notifications against the pinned ACP schema
and Relay's event normalization. Do not infer the original command error from
the Failed badge. Raw event evidence is retained outside Git under the test
directory; it may include provider diagnostics and is not a publishable file.

### W1: Windows patch-created files are unreadable

Provider/tool integration finding, not yet attributed to Relay.

The agent's patch tool created three new TypeScript files, including
`tests/helpers/windows-memory.ts`, that ordinary commands could enumerate but
could not read. `Get-Content`, `Get-Acl`, and read-only `icacls` returned
Access denied. Existing files modified by the same agent remained readable.
The helper was an ordinary 2,063-byte file, not a directory or link.

The agent independently reported the same failure during checks and recreated
its three new files through its command runner. All three became readable and
the checks passed. No permission mode, ACL, or global security change was
applied by the testing agent. This workaround belongs in the reproduction
record; it does not establish that the patch-tool defect is fixed.

### R3: saved workflow names leave the picker and sidebar stale

Priority: P2. Confirmed in the browser and API.

Replace the workflow YAML name with `Windows controls smoke` and save. The
editor header and launch dialog show the new name, and `GET /api/workflows`
returns it. The workflow picker and sidebar still say
`SuspendIt Windows memory regression`. Refresh their inventory after a
successful save that changes the name.

### R4: run remains in human-wait state after continuing

Priority: P2. Confirmed in a separate controls run.

Run `b8869f39-5a55-4ceb-9262-e7380bc037fc` executes a PowerShell script,
waits for a browser answer, and starts a long-lived Python parent and child.
Choose Continue in the browser. The wait succeeds, the parent job and next
command are running, and `waiting_count` is zero. The run status remains
`paused_wait`, and the browser still says Waiting for you for more than
20 seconds. The next command's printed process IDs and OS creation records
prove it has started. Reconcile the run's status when the wait resumes.

Setup observations, not defects:

- The Codex CLI was installed but its ACP adapter was absent. A test-local
  adapter installation made discovery and the model probe pass.
- SuspendIt explicitly skips renderer-memory checks on Windows because its
  current measurement invokes POSIX `ps`. This is the improvement under test.

## Run evidence

Run ID: `c52c065d-96a0-43d1-8f39-8edb76b17abe`.
Branch: `relay/run/c52c065d-96a0-43d1-8f39-8edb76b17abe`.
Agent commit: `1c3174423cd2c120e3963b6df6647d966b946f40`.

The commit changes six intended test/helper/documentation files. No runtime
extension dependency or behavior changed. The source checkout remains on its
original `main` commit. Workflow and prompt sources remain untracked there.
The run uses `retain`; no automatic merge or push is enabled.

The agent completed quality, unit/integration, packaging, and all four Windows
memory cases. Its first pass observed 135.4-136.1 MiB growth and 187.7-191.0
MiB release within 23.0-23.7 seconds. Each case also passed heartbeat,
awake-neighbor, discarded-placeholder, and explicit Resume assertions.

Relay's subsequent command steps independently passed `pnpm quality`, all
120 unit/integration tests, and `pnpm package`. Production-source coverage was
100% statements, 98.19% branches, 100% functions, and 100% lines. The package
was 42,704 bytes, with 24,162 bytes of JavaScript, inside the existing limits.
The final memory command passed all four cases in 1.9 minutes. It measured
135.3-136.1 MiB growth and 187.5-188.3 MiB release within 23.3-23.7 seconds.
The run reached `succeeded` at 12:45:26 EDT. The retained worktree is clean.

Browser Pause and Resume toggled durable dispatch state while the current
agent continued. A POST cancellation request without CSRF received HTTP 403
in no-login mode, leaving the run active.

The separate controls run skipped its conditional agent step, ran a real
PowerShell script with exit code 0, paused for a browser answer, and continued
after Continue. Its parent PID 46360 and child PID 36160 were observed alive
with creation timestamps before cancellation. Browser cancellation completed
at 12:48:00 EDT. At 12:48:15, neither process nor launcher PID 48208 existed.
No unrelated process was stopped. The canceled run's worktree is retained.

The useful workflow source was restored after capturing the controls run.
Its SHA-256 matches the successful run's captured workflow hash exactly.
Both runs keep their original immutable launch snapshots. The isolated Relay
test instance remains running on port 7845 with the successful run open.

See the [structured measurements](2026-10-14-windows-suspendit.json),
[successful run screenshot](2026-10-14-windows-suspendit.png), and
[stale wait-state screenshot](2026-10-14-windows-wait-state.png).

These results cover live Codex execution and command cancellation on this
Windows host. They do not certify the other four providers, ACP permission
callbacks, live agent cancellation, quota recovery, or the full OS/Python
matrix. The four Relay findings and the patch-tool finding remain open;
this task records them without changing Relay's implementation.

Report validation passed: file-scoped pre-commit hooks, Markdown lint,
spelling, local document links, and Git whitespace checks. Relay's code and
index remain unchanged; only this test's evidence files are untracked.

Baseline SuspendIt browser run: all 13 `extension.spec.ts` tests passed on
Windows with Chrome for Testing 153.0.8010.12, in 21 seconds. These cover
protection, suspension, active-tab handoff, restoration, browser restart,
selected/group/window scopes, local files, and popup layouts. This baseline
does not cover the newly implemented memory measurement.
