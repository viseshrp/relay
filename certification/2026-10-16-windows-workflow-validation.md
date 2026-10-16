# Windows workflow validation

Date: 2026-10-16. Implementation checkpoint:
`de3a85a6f4cc500c4174d0c93e3c9673fbba78f3`.
[Structured results and hashes](2026-10-16-windows-workflow-validation.json)
identify the source trees, test inventories, JUnit reports, browser reports,
and captured images.

Workflows execute jobs and ordered steps in a shared run workspace. Relay
commits changed code at a successful job boundary. Execution uses one worker;
the owner settings describe configurable values only. Activity shortens the
recorded run root and preserves subdirectory names. Agent guidance describes
the same workspace and commit rules.

Validation used Windows 11 build 26300, Python 3.14.7, uv 0.12.5, PowerShell
7.6.5, Node 20.20.2, Node 24.12.0, and Playwright 1.63.0. Every execution used
disposable repositories and storage. Frontend builds and tutorial captures
went to scratch directories.

| Check | Result |
| --- | --- |
| Complete native Python suite at `cf92391` | All 2,811 cases verified: 2,779 passed, 32 skipped, no failures |
| Serial contention and recovery lane | 49 passed, two skipped |
| Parallel lane, three isolated pytest workers | 2,730 passed, 30 skipped |
| Focused execution, configuration, settings, and editor checks | 195 passed, six symlink-privilege skips |
| Workflow-language boundaries | 55 passed |
| Final workspace guidance and job commit checks | Four passed; ACP and native Antigravity receive the complete workspace instructions |
| Dashboard, navigation, launch, guided workflow, settings, and presentation | 37 passed |
| Final activity and presentation checks | 27 passed; 58 distinct browser cases across both scopes, without skips or retries |
| Welcome capture generator | Passed; four screenshots, with every highlight inside its image |
| Fresh database | Migrations apply; model state matches; `makemigrations --check --dry-run` reports no changes |
| Python types | Linux, Windows, macOS, and the combined platform target pass |
| Repository and frontend quality | Hooks, locked dependency check, TypeScript build, ESLint, Prettier, documentation links/examples/transitions, and diff checks pass |

The full Python run tested `cf92391`. The later `de3a85a` change updates agent
workspace guidance, activity path presentation, two docstrings, and their
tests. Four focused Python cases and the final 27 browser cases cover that
change. Both Node runtimes execute in the complete Python run. Its 32 skips
comprise 22 unavailable symlink-privilege cases and ten platform cases. The
real Windows junction regression passes.

The scan covered tracked implementation, API/UI, tests, fixtures, scripts,
project documentation, and certification records. Callers and persisted
fields were traced before removal. The three owner review documents remain
byte-for-byte unchanged. No owner database, credentials, provider account,
browser profile, or served frontend assets were changed.
