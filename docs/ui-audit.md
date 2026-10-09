# UI audit follow-up

The three native Computer passes completed on October 7, 2026. Pass 1
covered project switching, workflow authoring and every Settings section.
Pass 2 covered run history, summaries, job logs, search, artifacts and
GitHub Actions comparison. Pass 3 used disposable repositories, isolated
storage and fake agents for saves, launch preflight, live command output,
approval, retry, cancellation, settings validation, login and sign-out.

Owner runs were inspected without launching, retrying or cancelling them.
Rebuilding exposed a stale asset catalog; an orderly runtime restart kept
25 runs, 25 snapshots, 183 attempts, 506 artifacts, settings and the paused
state. Connection and native control failures are not counted as app bugs.

## Confirmed issues

- [x] Switching to a project with no successful runs changes the workspace.

  Reproduce by opening a project with run history, then selecting an empty
  project in the project dropdown. Previously, a large Get started checklist
  appeared above the workflow sidebar and editor. The condition depended on
  successful runs in the selected project, making one application look like two
  different interfaces.

  Every project now keeps the same workspace. A small welcome prompt is shared
  across projects in that browser. Opening or dismissing it hides it after
  project switches and reloads. The full checklist opens in a dialog.

- [x] An incomplete checklist has no close control.

  Previously, Close checklist appeared only after a successful run and only when
  the checklist had been reopened from Help. Owners could not dismiss it when an
  agent was unavailable or when they wanted to use the editor.

  Close checklist is always available. Escape and the dialog backdrop also close
  it. Keyboard focus returns to Help, including after a failed agent check.
  Launching a starter closes the checklist and opens its run.

- [x] Selecting an empty project automatically probes installed agents.

  The inline checklist mounted when a project had no successful runs, so a
  presentation change also started provider connection checks. Previously, there
  was no explicit choice to open setup first.

  The checklist now mounts only when opened from the welcome prompt or Help.
  Project switching and reloads do not initiate its connection checks. An
  inventory response arriving after closure cannot start a new check.

- [x] Help cannot open Get started from Settings.

  The Help menu offered Get started on every page, but rendering excluded
  Settings. Selecting the menu item there had no visible result.

  The same dialog now opens from Help on Settings, Workflows, and Runs.

## Verification

The behavior reference is [Get started](web-ui.md#get-started).

The browser regressions in
[project-setup.spec.ts](../frontend/e2e/project-setup.spec.ts) cover the empty
project workspace, persisted dismissal, absent automatic probes, closing an
incomplete checklist, focus return, opening from Settings, failed checks,
and closing before a delayed inventory response. The existing starter
specifications still cover all six template runs and
readiness retry behavior using disposable repositories and fake agents.

## Decisions

1. Keep one workspace for every registered project. Run history does not
   choose a different layout.
2. Keep the welcome choice in browser storage, shared across projects on that
   Relay origin. It is a presentation preference, not a workflow default.
3. Put the detailed checklist in a dialog so opening it does not move the
   workspace. Keep it available from Help after dismissal.
4. Start connection checks when the owner opens the checklist. Preserve the
   existing bounded probe and launch validation services.
5. Apply repair settings only on Done. Prompt files keep their explicit Save
   instructions action; atomic workflow/prompt saving is outside this patch.
6. Stream bounded UTF-8 chunks without changing process ownership,
   cancellation, snapshots or execution states.
7. Inspect captured workflow YAML; make editing the current source a separate
   action so run evidence cannot be mistaken for a mutable draft.
8. Browse only resolved home directories. Keep manual repository entry for
   supported paths outside the browser root.
9. Create valid control-job scaffolds. Conditions return declared string
   labels; the default loop is bounded to one iteration.
10. Preserve the owner's backlog and root planning documents unchanged and
    unstaged. Record this audit in its own document.

## Findings from the three passes

- [x] UI-05 — Local runtime (P1)

  Rebuilding frontend while the editable server is running leaves the new asset
  hashes outside its startup catalog; reloading produces a blank page.

  Reproduce: Build frontend, keep relay up running, reload the owner tab.

  Expected: Current frontend loads after a build or restart.

  Observed: After normal reload, AX contains only HTML content Relay; screenshot
  is blank.

  Screenshot: `02-rebuilt-assets-not-served`.

  Fixed and verified: The static catalog discovers rebuilt hashes and rechecks
  resolved containment. tests/test_static_assets.py covers rebuilds, missing
  files, symlink swaps and traversal. The rebuilt owner UI loads successfully.

- [x] UI-06 — Workflow editor (P1)

  Opening Repairs for a job with no repair rule starts with Enable automatic
  repairs on. Opening the dialog itself adds a repair rule and marks the
  workflow Unsaved without an explicit opt-in. Escape does not undo it.

  Reproduce: Open Explore > Repairs, then close with Escape.

  Expected: Inspection and closing leave the YAML unchanged; adding a repair
  rule requires an explicit choice.

  Observed: Save changes from disabled to enabled and status reads Draft valid
  Unsaved.

  Fixed and verified: Repair settings stay in the dialog until Done. New rules
  start disabled; opening, Escape, Cancel and unchanged Done preserve exact
  YAML. frontend/e2e/ui-audit.spec.ts and repair-rules.spec.ts cover opt-in,
  cancellation and prompt saving.

- [x] GAP-01 — Project setup (P2)

  Open a project offers only a Repository folder text field; there is no
  directory browser.

  Reproduce: Choose Open another project.

  Expected: A beginner can choose a repository folder without typing an absolute
  path.

  Observed: Only Repository folder, Cancel, and Open project appear.

  Fixed and verified: Open a project browses paginated directories under the
  owner home folder, resolving symlinks before containment checks.
  tests/test_project_folders.py and frontend/e2e/ui-audit.spec.ts cover
  bounds, denied paths, symlinks, authentication and folder selection.

- [x] UI-07 — Empty workflow workspace (P2)

  A project with no workflows shows Editing unavailable and The workflow must
  contain a nodes mapping, although the user has not supplied invalid YAML. Run
  workflow remains enabled.

  Reproduce: Switch to relay, which has no saved workflows, and open Workflows.

  Expected: An empty state offers New workflow or a template; editing and launch
  wait for a workflow.

  Observed: Schema error and empty canvas shown immediately.

  Fixed and verified: Empty projects show No workflows yet, New workflow and a
  disabled Run workflow. frontend/e2e/project-setup.spec.ts checks the empty
  state and unchanged workspace layout across projects.

- [x] GAP-02 — Workflow editor (P2)

  Add a stage exposes only command, agent, and human review. Decision, loop, and
  subworkflow jobs have no creation option.

  Reproduce: Add stage > Stage action.

  Expected: Every supported job type can be created in the browser.

  Observed: Three menu entries: Run a command, Agent work, Ask for human review.

  Fixed and verified: Add a stage offers all six job types, with valid
  condition and bounded loop scaffolds and a saved-child selector.
  frontend/e2e/ui-audit.spec.ts saves and executes each new type. Nested loop-
  job definitions remain editable in YAML.

- [x] UI-08 — Run navigation (P2)

  Workflow filtering lives only in component state. Entering Runs with
  workflow=auto-suspend-uncapped.yaml displays All workflows; selecting that
  workflow changes the list without changing the URL.

  Reproduce: Enter Runs from the selected workflow; select its sidebar entry;
  reload or return later.

  Expected: A workflow URL restores the selected workflow and run list.

  Observed: The same URL represents both All workflows and the two-run workflow-
  specific list.

  Fixed and verified: Workflow filtering is stored in the URL.
  frontend/e2e/ui-audit.spec.ts checks reload, All workflows and Back
  restoring the selection.

- [x] UI-09 — Run graph (P2)

  The long run graph opens centered on middle iteration jobs, clipping both ends
  of the workflow; it does not offer a useful starting view.

  Reproduce: Open Summary for run #25.

  Expected: A readable initial view starts at the workflow entry or shows a
  compact overview with clear navigation.

  Observed: Screenshot starts with a cut-off iteration node and ends with
  another cut-off node; Prepare is off-canvas.

  Screenshot: `04-paused-run-summary`.

  Fixed and verified: Long graphs open at the entry job at readable scale.
  Short graphs fit normally and refresh preserves the viewport.
  frontend/e2e/run-graph.spec.ts covers entry visibility, selection and wheel
  behavior.

- [x] UI-10 — Job timing (P2)

  Skipped jobs show Not started in the graph’s duration position.

  Reproduce: Inspect Critique feedback (iteration 1) in run #25.

  Expected: Skipped jobs use a skipped label and no elapsed duration.

  Observed: Skipped icon with Not started where duration normally appears.

  Fixed and verified: Terminal jobs without a start time show an em dash for
  duration, with status icon and text preserved. frontend/e2e/run-
  graph.spec.ts covers skipped timing.

- [x] UI-12 — Empty job logs (P2)

  A paused dispatched job with no attempt shows Retry log history and Log
  history incomplete instead of a clean waiting-for-start state.

  Reproduce: Open Verify fixes (iteration 1), marked Starting in paused run #25;
  click Retry log history.

  Expected: No attempt means no log history to load; show the waiting
  explanation without a recovery error.

  Observed: 0 messages, Output will appear when this job starts, plus Log
  history incomplete; retry makes no visible change.

  Fixed and verified: No-attempt jobs show a clean waiting or did-not-run
  message and a disabled attempt selector, without history recovery controls.
  frontend/e2e/ui-audit.spec.ts covers this state.

- [x] UI-14 — Artifacts (P2)

  Repeated artifact names have no originating job or attempt; all download links
  have the same accessible name.

  Reproduce: Open run #25, choose Artifacts, inspect commits and worktree_diff
  rows.

  Expected: Identify each artifact by job, attempt and name, with a distinct
  download label.

  Observed: A flat list repeats commits/worktree_diff and raw byte/hash text
  with Download links.

  Fixed and verified: Artifacts identify job and attempt, readable size and a
  distinct download label. API fields are additive. tests/test_web_api.py and
  frontend/e2e/ui-audit.spec.ts cover provenance and download labels.

- [x] UI-15 — Run workflow file (P1)

  Workflow file leaves the run and opens the mutable authoring draft.

  Reproduce: On paused run #25 click Workflow file.

  Expected: Inspect the immutable workflow captured for this run, with a
  separate action to edit the current source.

  Observed: URL switches to view=workflows and shows an unsaved editable draft.

  Fixed and verified: Workflow file shows read-only captured YAML with its
  full hash and a separate Edit current workflow action. tests/test_web_api.py
  covers immutability, preview bounds and authentication; frontend/e2e/ui-
  audit.spec.ts covers changed source and focus return.

- [x] UI-16 — Navigation history (P2)

  Moving between views and runs replaces browser history instead of adding
  navigation entries.

  Reproduce: From a run choose Workflow file, then try browser Back.

  Expected: Back restores the prior run and selected job/filter.

  Observed: Chrome Back is disabled; only the latest Relay URL remains.

  Fixed and verified: User navigation adds history entries; normalization
  replaces the current entry. Back and Forward flush recovery drafts before
  restoring the view. frontend/e2e/ui-audit.spec.ts covers views, filters,
  summaries and job pages.

- [x] UI-17 — Live command logs (P1)

  Command output is withheld until the subprocess exits.

  Reproduce: Launch an unbuffered command that prints 161 lines, then blocks on
  a fixture release file. Open its log and refresh while it remains running.

  Expected: Each flushed line appears while the command is running, with search
  and follow latest available.

  Observed: Live logs stays at 0 lines for 20 seconds; all 162 lines appear only
  after the command is released and exits.

  Fixed and verified: Commands emit bounded stdout/stderr chunks while
  running, with independent readers and incremental UTF-8 decoding.
  tests/test_engine_scenarios.py checks pre-exit output, split UTF-8, large
  output, cancellation and timeout retention using socket handshakes. Native
  verification showed searchable output before exit.

- [x] UI-18 — Job log labels (P2)

  Human-wait jobs display an Agent conversation section.

  Reproduce: Open the completed Approve job in the disposable audit run.

  Expected: Human-review details and response, without agent-specific log
  headings.

  Observed: Agent conversation appears for a human_wait job.

  Fixed and verified: Human-review headings and log names say Human review.
  Agent and command labels stay distinct. frontend/e2e/ui-audit.spec.ts,
  activity-feed.spec.ts and actions-layout.spec.ts cover the heading and
  searchable log.

- [x] UI-19 — Recovery draft restoration (P1)

  Returning the YAML editor to its saved text leaves an older recovery draft in
  storage. Reloading brings the unwanted edits back. There is no discard control
  to clear an accidental edit without rewriting the source file.

  Reproduce: Edit YAML, wait for Draft valid, paste the exact saved YAML, then
  reload the workflow.

  Expected: The restored bytes replace the recovery draft. Discard changes
  restores the saved file without editing it.

  Observed: Dirty becomes false, so the draft write is skipped and the old
  recovery text remains.

  Fixed and verified: Restored saved YAML replaces an older recovery draft
  even when the editor becomes clean. Discard changes writes only the draft
  through existing lease/hash checks. frontend/e2e/ui-audit.spec.ts checks
  exact bytes, hashes and reload. The owner draft was restored through the UI
  and verified equal to the unchanged source file.

## Verification tooling follow-up

- [x] QA-01 — Dependency scan after the Python matrix (P2)

  Reproduce: Run make test, then make check. Tox creates .tox environments
  containing installed third-party Python files.

  Expected: Dependency checks scan Relay source; installed dependencies are
  checked by the lockfile, vulnerability and license gates.

  Observed: Deptry scans 14,494 files inside generated environments and
  crashes on a third-party relative import with an empty distribution name.

  Change: Add the generated .tox directory to the existing virtual-environment
  exclusions. Relay source rules and every quality hook stay enabled.

  Verified: `uv run deptry .` scans 122 Relay files successfully; the
  focused new-file hooks and `make check` pass.

## Delivered changes

All 19 UI findings above and the dependency-scan follow-up are fixed.
The owner backlog remains unstaged and unchanged.

| Findings | Commit |
| --- | --- |
| Four project/checklist findings | `ddc129f` |
| UI-05: rebuilt static assets | `df93e76` |
| UI-17: live command logs | `adba725` |
| UI-06, UI-07, UI-08, UI-09, UI-10, UI-12, UI-14, UI-15, UI-16, UI-18, UI-19, GAP-01, GAP-02 | `1e6223b` |
| QA-01: generated environment exclusion | `74944a1` |

## Final checks

| Command | Result |
| --- | --- |
| `make check` | Passed all enabled quality hooks |
| `uv run pytest tests -q` | 1,286 passed; one Windows-only skip on macOS |
| `npm --prefix frontend run build` | Passed TypeScript and Vite build |
| `make test-frontend` | 137 login-enabled and two no-login tests passed |
| `make test` | Python 3.10–3.14: 1,286 passed and one skip each |
| `make build` | Built wheel and source archive |
| `make check-dist` | Passed metadata and archive content checks |
| `uv run python scripts/check_doc_links.py README.md CONTRIBUTING.md docs/*.md` | Passed |
| `uv run python scripts/check_workflow_examples.py docs/workflows.md` | 16 guide examples and six starters validated |
| `uv run cog -r README.md` | Passed; generated help unchanged |

Each implementation commit also passed the linter and its focused
regression checks. Earlier browser failures included outdated human-review
labels and a reload during a concurrent asset build; the corrected full
browser rerun passed. The initial dependency hook failure is recorded in
QA-01, including its cause and verification.

Native isolated validation showed flushed stdout and stderr before command
exit. Search retained its active match as more lines arrived. All 164 lines
were retained, the approval form continued the run, and its summary reached
Complete. A captured-workflow dialog showed the frozen source separately
from the current-source editing action.

## Contract changes

The two owner-authenticated read endpoints and artifact metadata fields
are additive and documented in [HTTP API](http-api.md). Existing cursors,
event payloads and download routes are preserved. Commands publish their
existing output events earlier; their execution, ownership and cancellation
rules are unchanged. Browser history now records navigation, and the
workflow filter survives in the existing URL parameter. No database
migration, schema version, CLI contract or dependency was added.

## Audit limits

The native passes exercised the available controls. Destructive retained data
deletion was previewed, without deleting owner evidence. Live provider
authentication and execution were not certification runs. Folder browsing and
job-type creation were verified with isolated storage. Nested loop-job
definitions still require YAML. This audit does not claim every original
beginner-experience item is complete or certify live providers or other
operating systems.
