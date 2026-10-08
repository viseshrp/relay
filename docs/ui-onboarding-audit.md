# Settings, help, and first-use UI audit

This follow-up covers the workflow sidebar, all settings sections, first-use
screens, and inline explanations. The earlier workflow and run audit remains
in [UI audit](ui-audit.md). This checklist is separate from the owner's
unfinished product backlog.

## Inspection method

1. Used native Computer Use in Chrome against the running local installation.
   Compared the attached long-name sidebar with the actual workflow list.
   Opened Global defaults, Project defaults, Server and account, Notifications,
   and Storage. Expanded repair defaults and inspected their controls.
2. Added the changes, rebuilt the assets, and revisited Chrome. Navigated the
   welcome slides with buttons and the keyboard, opened and skipped the
   spotlight tour, read a settings tooltip, closed it with Escape, and checked
   the updated workflow sidebar and server-settings layout.
3. Added isolated browser regression coverage for first-use state, every tour
   step, replay/reset, empty projects, narrow screens, layout, and failed
   workspace loading. These tests use disposable repositories and fake agents.

Live inspection did not save owner settings, launch jobs, answer pending
requests, or delete run data. The supervisor was not restarted: rebuilding
frontend assets is sufficient for this editable installation. Automated
browser tests never use the owner's running instance or agent credentials.

## Bug checklist

- [x] Long workflow names shrink the document icon and shift text indentation.

  Reproduce: open a project whose workflow list contains both a short name and
  a title spanning three lines. The long title's icon becomes much narrower,
  and its first line no longer aligns with short titles.

  Fix: list icons cannot shrink, every row reserves the same icon column, and
  text wraps with a consistent line height and row gap. Native Chrome confirms
  the attached example now uses equal-size icons. The long-name browser test
  checks icon width and alignment.

  The full browser suite also caught a regression in the first spacing patch:
  a broad padding rule flattened nested loop-job indentation. Horizontal
  workflow-list padding is now scoped to the authoring sidebar; run-job depth
  keeps its existing indentation, verified by the job-history regression.

- [x] The settings save bar can cover the form while scrolling.

  Reproduce: open Global defaults, expand repair defaults, and scroll through
  the instructions. The sticky footer can float over controls being read.

  Fix: save controls follow the form in normal document flow. Narrow screens
  stack the buttons. The layout regression waits for expanded content and
  verifies the save button sits below the verifier field.

- [x] Automatic recovery sits too close to the retry field's floating label.

  Reproduce: read the job-default controls in Global defaults. The recovery
  switch row touches the label immediately beneath it.

  Fix: reserve vertical space between the switch and retry limit; keep help
  buttons in a separate column. The regression checks a minimum visible gap.

- [x] Collapsed settings groups do not clearly indicate that they expand.

  Reproduce: inspect agent settings, repair defaults, or advanced command
  arguments without clicking their headings. The disclosure action lacks a
  visible direction marker.

  Fix: add chevrons to expandable settings and advanced fields. Tour steps can
  open repair defaults for inspection without changing their saved values.

- [x] Closed agent-settings groups can initialize hidden configuration probes.

  Found while checking the tour's side effects: collapsed accordion contents
  still mount their configuration component when a saved model is present.

  Fix: let the accordion unmount closed contents. Opening a group explicitly
  loads its choices. The tour test starts with saved model/effort defaults and
  verifies that visiting the provider overview makes no configuration requests.

- [x] Settings sections reuse a description about global defaults.

  Reproduce: switch from Global defaults to Server and account or Storage.
  The heading changes while the introductory description remains unrelated.

  Fix: each settings section explains its own scope, including restart needs,
  browser preferences, project inheritance, and confirmed storage cleanup.

- [x] The no-login account page claims that the browser signed in as local.

  Reproduce: use an installation with login disabled and open Server and
  account. The local-access identity appears as though it were a sign-in.

  Fix: describe local access without claiming authentication. The no-login
  introduction test checks this text and confirms no owner account is created.

- [x] Rebuilding can leave an already-open tab blank on workspace navigation.

  Reproduce: keep a tab open across a frontend rebuild, then open a workspace
  whose old JavaScript chunk has been replaced. A rejected lazy import can
  remove the application instead of presenting a recovery action.

  Fix: a workspace error boundary shows a public explanation and an explicit
  Reload Relay button. It does not automatically reload or expose exception
  details. A regression aborts the workspace request, checks the error, then
  restores the request and verifies reload recovers the editor.

- [x] Closing the welcome screen with Escape also closes the following tour.

  Found during regression testing: the dialog handles Escape on keydown while
  Driver.js handles it on keyup. One keypress can dismiss both introductions.

  Fix: complete the welcome screen's Escape handling on keyup before mounting
  the tour. The regression verifies separate Escape dismissal and persistence.

- [x] Replayed welcome slides offer a tour button that only closes the slides.

  Found during review: the original finish callback closed the carousel but
  did not request a tour when that tour had already been seen.

  Fix: Show guided tour explicitly requests the tour, including from replay.
  The mobile regression verifies replay can start it again.

- [x] A dismissed help tooltip can reopen immediately on its focused button.

  Found during keyboard testing: library hover/focus handling can reopen a
  controlled tooltip immediately after Escape.

  Fix: retain dismissal until the pointer leaves or focus changes, while
  keeping explicit click reopening and interactive hover support. The test
  checks Escape dismissal and focus retention beside a disabled control.

## Added first-use behavior

- [x] Empty installations explain the path to a first run.

  With no registered projects, show the homepage with repository, agent,
  workflow, and run steps. Open your first project opens the existing folder
  dialog. Global settings remain accessible. Registered projects continue to
  use the shared workspace layout even when they have no workflows.

- [x] Welcome slides introduce four important areas.

  Embla Carousel React 8.6.0 supplies the carousel. Four local SVG illustrations
  highlight projects, workflow creation, log search, and global defaults.
  There is no automatic slide advancement. Buttons, arrow keys, and swipe
  gestures use the library's navigation.

- [x] A spotlight tour explains navigation and settings.

  Driver.js 1.9.0 supplies the overlay, spotlight, scrolling, and popovers.
  The tour has 27 steps with Next, Back, Skip, progress, and Finish. It opens
  the needed settings sections, keeps keyboard focus in tour controls, and
  prevents editing highlighted settings. Agent effort and permissions are
  explained at the provider group without probing provider sessions.

- [x] Dismissal persists and either introduction can be replayed.

  Record each as seen when it opens. Help and Settings can replay them
  separately. Settings > Welcome and guided tour can reset both for the next
  opening. Skipping and reloading do not repeat a seen introduction.

- [x] Question-mark help explains settings and workflow controls.

  A shared catalogue explains defaults, exact models, permissions, command
  argument lists, variables, timeouts, recovery, cleanup, repairs, workflow
  dependencies, outputs, logs, and launch controls. Disabled fields retain
  usable help. The explanations describe the existing Python contracts.

## Decisions

1. Keep first-use flags per browser and installation address. They are UI
   preferences and do not belong in project files, execution snapshots, or
   the owner database. If browser storage is blocked, dismissal lasts for the
   current session and reset reports that persistence is unavailable.
2. Mark an introduction seen when it opens. Reloading midway does not force
   someone through it again; replay and reset remain available.
3. Keep the existing optional Get started checklist for agent checks and
   templates. The carousel introduces the app; the tour explains settings;
   neither silently starts provider sessions.
4. Keep owner colors and fonts. Welcome images now use real screenshots from
   disposable projects, with blue highlights measured from the controls.
   `npm --prefix frontend run capture:welcome` regenerates these images.
   Owner projects and provider output remain outside the image fixtures.
5. Pin the two requested libraries through npm. Embla's two supporting
   packages and Driver.js use MIT, which the repository permits. No backend
   dependency, workflow schema, migration, or execution rule changes. A later
   additive dashboard read exposes saved project activity.
6. Recover failed workspace loads through an explicit reload. This leaves the
   decision with the user and preserves browser workflow recovery drafts.

## Verification

Focused cases live in `frontend/e2e/onboarding.spec.ts`. Existing settings,
workflow, run, login, and no-login tests continue to use the same isolated
server, with introductions marked seen for tests of unrelated behavior.
Screenshots from these tests contain disposable fixture data. They complement
native Chrome inspection; they are not screenshots of the owner's instance.

The tour test visits every step, checks that each spotlight has a real target,
checks keyboard containment, and rejects unexpected settings, launch, or agent
configuration writes. Additional cases cover mobile layout, independent
replay, reset, empty inventories, blocked storage, and failed chunk loading.

The native audit is not a claim that every possible workflow, installed
provider, or operating system was exercised. No live provider certification
or Windows/Linux UI run was performed for this frontend change.

## Dashboard and help placement follow-up

- [x] Home shows saved work across registered projects and the Relay logo
  returns there. Waiting cards open their exact request. Active and paused
  runs, recent results, project search, pagination, and durations share the
  existing status mapping. A missing remembered project falls back to an
  available project on Home. `frontend/e2e/dashboard.spec.ts` covers navigation,
  recovered drafts, answering requests, failed refreshes, and hidden tabs.
- [x] Help no longer occupies a separate column beside wide fields. Labels
  and help sit above text and select controls; switches and actions retain
  their own adjacent help. `frontend/e2e/help-layout.spec.ts` checks alignment
  at 320, 390, 760, and 1,440 pixels, tooltip containment, keyboard dismissal,
  equal input alignment with different helper text, and unchanged settings
  after help clicks.
- [x] Early Escape or Skip closes the requested tour even before Driver has
  finished highlighting its first element. Replaying welcome slides keeps a
  dismissed tour dismissed. The replay regression covers this behavior.
- [x] Welcome slides use real fixture screenshots in a desktop split and a
  mobile stack. The capture validates rendered fonts and control bounds;
  browser checks validate decoded images and contained blue highlights.
- [x] Concurrent discovery requests use separate staging files for registry
  refreshes. The shared temporary filename caused an intermittent startup
  error in the no-login starter test. `tests/test_agent_domain.py` coordinates
  both writers at publication and covers failed writes with and without a
  previous cache. The registry behavior is described in `agents.md`.

The username menu holds settings and help when signed in. Optional no-login
access keeps its settings tab and Help button without the old header label.
`tests/test_dashboard.py` covers additive, bounded reads, actionable counts,
cursors, empty projects, authentication, and database errors. Behavior is
specified in `web-ui.md` and `http-api.md`.

## Control sizing and data hierarchy audit

This audit used three native Computer passes: inspect the running app, exercise
forms in a disposable installation, and revisit rebuilt screens. The running
app checks covered Home, the project switcher, workflow sidebar and editor, run
history, paused summary, command logs, and all six Settings sections. Editing
checks covered expanded provider defaults, command and environment editors,
repair dialogs, all six job types, launch options, and the folder picker. The
onboarding check visited all four welcome slides and all 27 tour steps.

### Findings and fixes

| Status | Reproduction and defect | Change and regression coverage |
| --- | --- | --- |
| Fixed | Select a short project name. The header picker shrinks almost to its text and changes width between projects. | Give the picker a stable desktop width and a bounded mobile width. `control-layout.spec.ts` checks both the picker and long workflow names. |
| Fixed | Open a long workflow or cleanup choice. The selected value expands the field height, and menu text can overflow on a narrow screen. | Keep selected values on one line; wrap menu options within the viewport. Check open menus, selected heights, and Escape focus return at 320 through 1,440 pixels. |
| Fixed | Open defaults, a new agent job, run filters, or launch options. Empty selectors look like blank inputs with no explanation of inheritance. | Show the existing default choice or a named placeholder. Tests check models, repairs, dependencies, launch defaults, history filters, and empty Storage lists. |
| Fixed | Open Server and account or recovery settings. Port, worker, timeout, and retry fields use the same large widths as prose fields. | Bound short controls to 144 pixels and preserve wider helper text. Keep normal desktop inputs under 40 pixels high. Touch targets remain larger. |
| Fixed | Expand shared commands, instructions, or condition branches. Add, remove, and save actions stretch across their containing stack. | Size actions to their text and let action rows wrap. Command and instruction saving keep their existing behavior. |
| Fixed | Open Storage. Labels, totals, sizes, and explanations have similar weight, and four metrics produce an orphaned row. | Use a two-column metric grid, a one-column mobile layout, muted labels and sizes, and stronger totals. Semantic label/value checks cover every metric. |
| Fixed | Open Home, Get started, folder browsing, or Storage. Full absolute paths dominate the page. | Show the final two path components with a keyboard-accessible disclosure and copy action. Tests preserve exact Windows path bytes and cover clipboard failure. Editable paths stay complete. |
| Fixed | Select a command job with many arguments. Its composite editor occupies one grid cell, leaving unused space while the textarea grows without limit. | Give composite editors a complete row and bound textareas to eight visible lines. Tests retain all 50 arguments and exact JSON/YAML values on narrow and wide screens. |
| Fixed | Open a run summary with enough jobs to use the top of the graph. The workflow heading overlays its first job. | Reserve a separate graph header above the canvas. A completed twelve-job run checks the heading and node bounds. |
| Fixed | Open saved repair roles. Agent, model, effort, and permissions are joined in a long sentence that hides the label/value distinction. | Give each role a heading and labeled rows. The paused-verifier regression checks exact saved values instead of workflow defaults. |
| Fixed | Change a job to a human review or result check when the workflow has no repairs mapping. The editor crashes while deleting a nonexistent nested YAML key. Removing a job has the same defect. | Delete a repair entry only when it exists. The regression changes one job through all six types and then removes it, at mobile and desktop widths. |
| Fixed | Search or scroll command logs, then open full screen. It renders the previous virtual line range at scroll position zero, leaving a large blank area. Returning can also lose the reading position. | Restore scrolling when the new viewport mounts. `actions-layout.spec.ts` checks visible search matches for commands and agents, exact scroll restoration in both directions, and unchanged downloads and live following. |
| Fixed | Open a workspace at 320 pixels with its welcome banner visible. The two actions squeeze the message into a narrow column. | Move actions below the message on small screens and let them wrap. `control-layout.spec.ts` checks message width and action placement before testing the dropdown. |

### Decisions

1. Keep the existing font family and colors. Compact controls, bounded widths,
   and stronger label/value hierarchy apply across the shared theme and forms.
2. Preserve exact paths, model values, arguments, and environment values.
   Truncation affects presentation; disclosures and editors keep the bytes.
3. Keep multiline fields scrollable. A long command or prompt must not push
   every subsequent setting hundreds of lines down the page.
4. Keep cleanup confirmation and ownership checks unchanged. Empty cleanup
   controls explain why they are unavailable rather than offering an empty
   menu. Audit actions never remove retained owner data.
5. Use separate rows for saved repair settings. These are captured values for
   the run, not editable controls or a new settings hierarchy.
6. Preserve log reading position when opening or closing full screen. Dialog
   content mounts after its opening render, so scroll restoration follows the
   viewport element rather than only the full-screen flag.

### Coverage

`frontend/e2e/control-layout.spec.ts` checks layout and behavior at 320, 390,
760, 1,440, and 1,920 pixels. Existing browser specs exercise tooltips,
settings persistence and conflicts, command defaults, repair rules, live log
search and downloads, onboarding, run controls, and cleanup failure recovery.
The welcome images are regenerated from the disposable app after the layout
changes so their measured highlights match its controls.

Native inspection uses the owner's app for read-only observations and the
disposable app for edits. Automated checks use fake providers and isolated
repositories. This pass does not certify installed providers or claim that
every possible workflow and operating system was exercised.

### Verification on 2026-10-08

| Command | Result |
| --- | --- |
| `make check` | Passed. |
| `uv run pytest tests -q` | 1,301 passed; one Windows junction test skipped on macOS. |
| `npm --prefix frontend run build` | Passed. |
| `npm --prefix frontend exec -- tsc --noEmit --noUnusedLocals -p frontend/tsconfig.json` | Passed. |
| `make test-frontend` | 165 login-mode tests and three optional-login tests passed. |
| `uv run python scripts/check_doc_links.py README.md CONTRIBUTING.md docs/*.md` | 13 Markdown files validated. |
| `uv run python scripts/check_workflow_examples.py docs/workflows.md` | 16 guide examples and six starter workflows validated. |
| `uv run cog -r README.md` | Passed; generated help unchanged. |
| `make build` | Wheel and source distribution built. |
| `make check-dist` | Passed. |

The served index, entry assets, and lazy run-workspace asset matched the rebuilt
files. The owner app stayed on the same processes. Comparison of 29 database
tables and retained file hashes preserved runs, snapshots, attempts, events,
artifacts, settings, resources, and worktrees. Only navigation timestamps,
supervisor heartbeats, and successful model-observation IDs and timestamps were
excluded; the observed models and configuration values were compared. All 17
protected owner documents stayed unchanged and outside the commits.

## Compact layout follow-up

This pass addresses the approved cleanup plan. Native Computer observations
use the running app for read-only checks and a disposable fake-agent app for
form edits, launches, and onboarding. Owner settings and run controls are not
changed during the audit.

| Status | Reproduction | Expected behavior and regression |
| --- | --- | --- |
| Verified | Resize below 1,050 pixels. The project picker becomes a 200-pixel-tall flex item. | Keep its flex direction horizontal, use two deliberate header rows, and measure header height for anchors. `control-layout.spec.ts` covers all six requested widths. |
| Verified | Open Storage with many completed runs. The menu nearly fills the page. | Bound the list and paper, scroll internally, separate run number/title/status, and retain every option. The 40-run menu regression reaches the final option and dismisses with Escape. |
| Verified | Scroll to the bottom of Global defaults, then select another section. | Bring its heading below the sticky header and focus it. The navigation regression checks position and focus. |
| Verified | Open project defaults. Repeated switch labels obscure the actual setting and inherited state. | Show a separate override row and inherited-state caption. `settings.spec.ts` retains exact inherited values and independently saved overrides. |
| Verified | Open models, timeouts, commands, and environment editors. Fields expand to the whole panel. | Use widths by purpose, retain wider numeric labels, and group model selection with its loading action. Existing six-form and command-byte checks remain in place. |
| Verified | Choose workflows or nested jobs with long names. Navigation occupies several lines. | Keep single-line labels with full accessible names and hover titles; retain nested-job context for assistive technology. |
| Verified | Open a job log. Title and attempt controls take separate full rows. | Use a responsive heading toolbar, compact output controls, and preserve live following, search, attempt selection, output colors, and manual scrolling. `actions-layout.spec.ts` checks search and full-screen restoration. |
| Verified | Open artifacts in a narrow run panel. Download actions are clipped. | Stack labeled artifact cells inside narrow containers. The regression reaches every download at six widths. |
| Verified | Open Workflow file from a run. Source uses the body font. | Use monospace while retaining captured bytes. Frozen-source and responsive artifact regressions cover it. |
| Verified | Open launch preflight with dirty Git files. Extended instructions overwhelm inputs. | Keep blockers visible and place Git instructions in a disclosure. `launch-panel.spec.ts` opens it and verifies copying does not change Git. |
| Verified | Expand launch options. The optional model field looks blank and unexplained. | Show an inheritance placeholder on the existing text/datalist control. The dialog regression checks it and help placement/dismissal. |
| Verified | View short POSIX, Windows drive, and network paths. They remain absolute in ordinary views. | Abbreviate display only; full disclosures and copy retain exact values. Path regressions cover all three forms and clipboard failures. |
| Verified | Open a top-level run graph. A synthetic Root completion node appears. | Exclude only the root scope from completion junctions. `run-presentation.spec.ts` retains real nested completions and loop ordering. |
| Verified | Build while a tab has not opened its lazy workspace yet. Its old chunk disappears. | Publish from staging, replace the entry page last, and retain earlier chunks. Publication tests exercise copy failure and an actual open browser tab. Clean wheel builds remain separate. |

### Decisions

1. Keep complete values in editors, captured source, disclosures, and copy
   actions. Abbreviation changes display only.
2. Use container width for artifact rows, because a run panel can be narrow
   inside a wide browser. Each download stays in the same semantic table.
3. Keep numeric inputs short while allowing their labels and explanations a
   wider area. Readability takes precedence over matching label width to input.
4. Keep an accessible compact empty waiting section on the dashboard. Show five
   recent results initially, with an explicit action to reveal the remaining
   loaded results and existing pagination.
5. Retain old hashed assets in editable checkouts. Distribution builds clean
   their output so releases do not collect earlier frontend versions.
6. Stage beside the output directory so source-map paths match clean builds.
   A real Vite regression compares the generated map bytes across both modes.

### Verification scope

Native coverage includes all Settings sections, four welcome slides, all 27
guided-tour steps, and all six job types. Browser regressions use isolated data
and fake providers. The results below separate native observations from
automated coverage. Provider certification and changes to execution,
authentication, schema, or HTTP payloads are outside this presentation pass.

### Three-pass results

1. Coverage: native Computer visited all six Settings sections, empty and
   populated projects, the dashboard, workflow navigation, all six job forms,
   prompts and repairs, launch options, template and folder dialogs, run
   summaries, job logs, artifacts, four welcome slides, and 27 tour steps.
   Saves and a successful launch used disposable data and a fake agent.
2. Interaction: native checks covered menus, help placement and Escape,
   disclosures, heading focus, dialog dismissal, log search and full screen,
   and an already-open tab entering a lazy workspace after publication.
   Isolated browser regressions covered dirty-form warnings, failed saves,
   cleanup ownership and failures, authentication, loading, and error states.
3. Responsive: native inspection repeated at 390, 760, 900, 1,050, 1,440, and
   1,920 pixels and at 200% zoom. Automated checks assert header bounds,
   menu height, artifact actions, compact fields, and 44-pixel touch targets.

The checks found and corrected a 36-pixel touch menu row and differing
source-map paths during staged builds. Updated browser assertions now check
settings-heading focus and the clarified inherited labels. These checks passed
with the final implementation.

### Final checks

| Command | Result |
| --- | --- |
| `make check` | Passed after the implementation commits. |
| `uv run pytest tests -q` | 1,301 passed; one Windows junction test skipped on macOS. |
| `make test` | Python 3.10, 3.11, 3.12, 3.13, and 3.14 each passed 1,301 tests with the same one skip. |
| `npm --prefix frontend run build` | Passed; published the editable frontend. |
| `npm --prefix frontend run test:build` | Four publication regressions passed, including a warm browser and real Vite source maps. |
| `make test-frontend` | 180 authenticated browser tests and three optional-login tests passed. |
| `uv run python scripts/check_doc_links.py README.md CONTRIBUTING.md docs/*.md` | 13 Markdown files validated. |
| `uv run python scripts/check_workflow_examples.py docs/workflows.md` | 16 guide examples and six starter workflows validated. |
| `uv run cog -r README.md` | Passed; generated help unchanged. |
| `make build` | Wheel and source distribution built. |
| `make check-dist` | Passed. |

### Live publication and retained data

The frontend was published while the existing owner app stayed on the same
processes. Its entry page and 679 asset files matched disk. All 660 earlier
asset files remained byte-for-byte unchanged. Native navigation through the
updated live app succeeded, and a disposable warm tab loaded its previously
unopened workflow workspace after publication without a reload error.

Comparison of 29 database tables and retained file hashes preserved 25 runs,
snapshots, attempts, events, artifacts, settings, resources, and worktrees,
including the paused run. Navigation timestamps, supervisor heartbeats, and
model-observation IDs and timestamps were excluded from that comparison;
observed models and configuration values were compared. The owner's backlog
remains unstaged, and all 17 protected owner documents remain unchanged.

### Screenshot evidence and limits

The delivered local evidence folder contains native before/after captures at
390 pixels, Storage before/after captures, an empty project, repairs, and the
warm tab after publication. Clean disposable browser captures include
`storage-desktop.png`, `storage-mobile.png`, `agent-editor.png`, `job-log.png`,
`run-summary.png`, and `artifacts-mobile.png`. Screenshots contain fixture data;
owner run output and credentials are excluded.

This verification covers native macOS Chrome and the isolated browser suite.
The Python matrix ran on macOS; it does not establish Windows or Linux runtime
certification. Installed provider accounts were not exercised. Existing Django
SSE and Vite bundle-size warnings remain outside this presentation change.
