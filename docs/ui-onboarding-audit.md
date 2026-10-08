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
4. Keep owner colors and fonts. Use illustrations with example labels instead
   of screenshots containing owner projects or provider output.
5. Pin the two requested libraries through npm. Embla's two supporting
   packages and Driver.js use MIT, which the repository permits. No backend
   dependency, API, workflow schema, migration, or execution rule changes.
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
