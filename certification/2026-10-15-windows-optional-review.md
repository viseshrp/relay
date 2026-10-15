# Optional review follow-up on Windows

Date: 2026-10-15. Product code checkpoint:
`772c9f91c2e35e123650ad9533e5af108d9b4c8c`.

This pass addresses S1 through S9 from the owner's review. The required B1,
B2, and N1 through N8 fixes remain documented in the
[preceding automated follow-up](2026-10-15-windows-end-to-end.md).

## Review concerns

| Item | Result | Change or evidence |
| --- | --- | --- |
| S1 | Fixed in `fe07d8a` | Check the tool-summary dictionary before JSON encoding; discard empty private-only updates. |
| S2 | Fixed in `d20ae45` | Structured tool exits and command steps use `Exit code: N`. |
| S3 | Fixed in `d20ae45` and `2d797e5` | Read integer raw-output exit fields, including zero and Cursor's camel-case field. Terminal metadata takes precedence; invalid values remain ignored. |
| S4 | Fixed in `e2449ab` | Production file selection uses `stat.FILE_ATTRIBUTE_REPARSE_POINT`; the real Windows junction regression passes. |
| S5 | Documented in `6c6ebae` | Explain that inherited `PYTHONIOENCODING` overrides standard-stream encoding. |
| S6 | Corrected in `6c6ebae` | The collection guard belongs to the native tox probe. Both nested probes set their own root and configuration boundary. |
| S7 | Live retests completed | Claude, Copilot, and Cursor passed authenticated Windows Actions diagnostics, exact-model proof, browser checks, report retention, job commits, and cleanup. |
| S8 | Fixed in `a7559ad` | The runtime owns event splitting; the general driver has no Actions dependency and preserves its per-part cancellation yield. |
| S9 | Fixed in `ed6831b` | Header management reuses the guarded inventory refresh. A delayed response cannot reselect an old workflow after browser Back. |

## Defects found during live testing

Cursor returned `{stdout, stderr, exitCode}` as structured raw output. Relay
retained those fields but omitted their output and exit code in the activity
view. Commit `2d797e5` displays them. Four regression cases failed before the
fix; all 21 activity-feed cases passed afterward. The actual Cursor workflow
also displayed its Unicode stdout, stderr, and exit code in the browser.

Copilot sent cumulative tool-content snapshots. An early snapshot retained a
prefix of a registered synthetic secret, even though the later snapshot masked
the full value. Commit `772c9f9` holds possible secret suffixes independently
for each output field. Replacements discard the preceding pending suffix;
completion and step shutdown flush a remaining safe suffix once. Five new
regressions failed before the fix. The corrected tests include nested raw
output, replaced fields, separate tools, shutdown, and large-event splitting.
The fresh Copilot command output contains neither the registered value nor
its previously exposed prefix.

Both fixes were retested through the production CLI, supervisor, worker,
HTTP API, and browser in disposable repositories and isolated storage. No
provider model, effort, or permission setting was changed to bypass failure.
The masking guarantee remains scoped to Actions execution.

## Windows verification

The host uses Windows 11 x64 build 26300, Python 3.14.7, Node 24.12.0,
PowerShell 7.6.5, Git 2.54.0.windows.1, uv 0.12.5, and Playwright 1.63.0.
A scratch Node 20.20.2 archive was verified against the
[official SHA-256 list](https://nodejs.org/dist/v20.20.2/SHASUMS256.txt) for the
separate JavaScript integration retest.

| Check | Result |
| --- | --- |
| Native tox, both Python 3.14 lanes | 2,982 collected: 2,944 passed and 38 verified skips |
| Initial focused agent/domain/file tests | 180 passed, one symlink-privilege skip |
| Final snapshot/driver/file tests | 120 passed, one symlink-privilege skip |
| Both declared JavaScript runtimes | 12 passed with Node 20 and Node 24 |
| Four ACP profiles and two output forms | Eight deterministic wire exchanges passed |
| Complete functional browser suite | 302 passed; all collected cases executed once |
| No-login / monitor unit / structural layout | 4 / 16 / 8 passed |
| Build-script and expression tests | 1,036 passed; five declared oracle cases skipped |
| Quality and documentation checks | Passed: hooks, Ruff, types, frontend build/lint/format, and documentation checks |

The complete native Python run used checkpoint `a3c6336`, before the snapshot
fix. Its 38 skips comprise 22 symlink-privilege skips, ten platform skips, and
six unavailable Node 20 cases. The separate runtime retest passed all twelve
Node 20/24 cases. The final focused run covers the snapshot fix; current full
OS/Python matrix results are reported on the pull request.

The native browser inventory and reports identify product checkpoint
`772c9f9`. The repository validator verified all 330 functional and auxiliary
outcomes with no missing cases, duplicate outcomes, skips, or automatic
retries. The test-only readiness amendments in `ce2ed46` were applied before
the accepted first shard and committed after verification. They change
fixture waits in `activity-feed.spec.ts` and `dashboard.spec.ts`; product
source files remain identical to `772c9f9`.

Windows has no pixel baselines. The 21 pixel comparisons remain Linux checks;
the eight native structural cases retain their accessibility, containment,
and layout-shift assertions. Accepted runs forbid snapshot updates.

The first concurrent browser pass recorded eleven readiness/time-limit
failures while the complete Python suite also ran. Those reports and traces
are retained separately. A subsequent run exposed a five-second completed-run
fixture wait in the Home paging case. The activity and Home fixtures now use
the existing bounded execution helper; UI assertions keep their own limits.
Another shard reported Chromium's `ERR_NO_BUFFER_SPACE` during navigation.
Its complete reports were preserved before rerunning that whole shard after
the other browser and Python processes stopped.
Whole shards are rerun, and accepted outcomes are never assembled from
individual passing cases in failed runs.

The new raw-exit and management Back regressions also failed against the
retained earlier frontend build. The corrected frontend passed both.

## Authenticated provider results

The [structured record](2026-10-15-windows-acp.json) includes exact versions,
selected values, source hashes, run IDs, report hashes, job commits, and cleanup.

| Provider | Binary or adapter version | Exact selected value | Output and permission evidence |
| --- | --- | --- | --- |
| Claude Code | Claude 2.1.300; ACP 0.91.0 | `default` | Terminal deltas, structured exit 3, two one-use approvals |
| GitHub Copilot CLI | 1.0.98 | `auto` | Cumulative snapshots, public exit-code footer, two one-use approvals |
| Cursor CLI | 2026.10.14-941492e | `default[]` | Structured stdout/stderr and exit 3, one one-use approval |

All three runs completed, wrote a required UTF-8 report, committed it once at
the successful job boundary, and advanced the protected head. Downloaded
artifact bytes matched their recorded hashes and the committed report. Source
checkouts stayed clean and unchanged. Relay removed each worktree through its
confirmed cleanup API and cleared provider process identities. All 24 artifact
downloads were verified again after cleanup. The final supervisor and its
owned children stopped cooperatively, and its ownership record was removed.

The exact selectors `default`, `auto`, and `default[]` do not identify concrete
backend models. Cursor omits an ACP agent version, so its command version is
recorded. Copilot provides its exit code in tool-content text; Relay displays
that footer without inventing a structured integer. Claude's advertised probe
deletion cannot be performed by the pinned ACP SDK, so provider-owned probe
history may remain.

The initial Copilot diagnostic reached its five-minute step deadline during
interactive validation. Its failed run and artifacts were preserved before
the fresh ten-minute diagnostic. The first harness supervisor required a
forced stop after its attempts ended and its worktrees were removed. The
final harness used a Windows process group and verified cooperative shutdown.
Live cancellation, elicitation, model drift, and provider timeout behavior
remain outside this short output retest. Antigravity remains unverified on
Windows; the historical Codex Windows run predates these review fixes.

Raw logs, native reports, JUnit XML, failure traces, hashes, and private
provider diagnostics remain under
`%TEMP%/relay-optional-review-9448165f6d/`, outside Git. The owner's three
untracked review documents retain their original hashes. Provider installation
and account sign-in were explicitly requested by the owner. The pull request
remains unmerged, with auto-merge disabled.
