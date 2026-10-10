# Beginner-experience backlog implementation

This index maps the completed findings in the owner's backlog to the current
Actions workflow format and focused regression coverage. Current workflows
use jobs, ordered steps, scripts, reusable workflows and local triggers.
Historical v1 snapshots retain their execution and monitoring contracts.
The [working backlog](todo.md) marks these findings complete.

| Findings | Implemented behavior | Focused coverage |
| --- | --- | --- |
| BX-03, FE-07, DT-08 | Shared workflow sidebar, selected workflow URLs, native navigation and job links, old author URLs | workflow-navigation, workflow-management, actions-layout, accessibility browser specs |
| BX-07, FE-06 | Schema-driven root/job controls, structured values, inputs, matrix, concurrency, step types, expandable loop/reusable graphs; advanced JSON remains available | workflow-authoring, actions-source, command-defaults browser specs; workflow-language and Actions schema tests |
| BX-08 | Highlighted multiline scripts, host shell selection, exact argument planner preview and preserved argv actions | workflow-authoring browser spec; test_actions_file_boundaries, test_actions_execution_contracts |
| BX-10 | One workflow-and-prompts Save, draft switching, discard, shortcut and atomic source bundles | workflow-authoring, editor-recovery browser specs; test_source_bundle |
| BX-12, BR-05, DE-07 | Readable job cards, type/status icons, agent/model details, durations, grouped fan-outs, page scrolling and explicit zoom | run-presentation, run-graph, visual-regression browser specs; test_web_api |
| BX-14 | Run numbers, titles, workflow/branch/status/search filters, relative dates and exact date titles | actions-layout, job-history, visual-regression browser specs |
| BX-15, BR-06 | Named artifacts, verified preview/download, paged file lists and download-all ZIP; empty internal evidence is hidden | actions-layout browser spec; test_web_api, Actions product/API tests |
| BX-17, QA-10, BR-09 | Shared status/icon vocabulary, queued state, started-only durations, day rollover and separately recorded pause time | run-presentation and visual-regression browser specs; test_web_api, dispatch-pause tests |
| BX-18, BX-19 | Plain-language defaults, exact model combobox and provider-derived effort choices | agent-configuration, accessibility, settings browser specs |
| BX-20 | Markdown preview, ordered local/global prompts, creation/reuse/rename-copy and prompt context | workflow-authoring browser spec; prompt source/snapshot tests |
| BX-21 | Visual/YAML/Split modes with completion, hover, diagnostics and reviewed formatting | workflow-authoring, editor-recovery browser specs |
| BX-22 | Connect/delete edges, keyboard node deletion, insertion, duplication, context menu, undo/redo and run from here | workflow-authoring browser spec |
| BX-23 | Stop/inherit/bounded retry choices and explicit reusable fix-and-check loops | workflow-authoring, automatic-recovery, repair-rules browser specs; recovery-policy tests |
| BX-24 | Bounded repository discovery, live Git checks and explicit Git initialization preserving files | project-setup browser spec; project discovery/initialization tests |
| BX-25 | Protected rename, duplicate, disable, enable and confirmed deletion | workflow-management browser spec; workflow management and trigger tests |
| BX-26 | Re-run all, failed or selected jobs with explicit launch/retry choices | run-actions, launch-panel, run-problems browser specs |
| BX-29, BX-35 | In-app guides, keyboard help, empty-state controls and three translated GitHub Actions examples | help-layout, get-started browser specs; documentation links/examples |
| BX-31, DT-07, DT-09, DT-10, DT-11, DT-12, FE-08 | Named controls, landmarks/headings, skip links, focus/scroll handling, text contrast and automated axe gate | accessibility and all browser specs |
| BX-32 | Session-scoped run/job disclosures survive updates and stay separate across runs | monitor-boundaries browser spec |
| BX-33 | Expression suggestions, value/operator builder and inline validation | workflow-authoring browser spec; Actions expression tests |
| BX-34, BR-02, BR-03, BR-08, FE-04 | Shared breakpoints, phone navigation, bounded pickers/cards and full-width job drawer | control-layout, visual-regression browser specs |
| BX-36 | Supported Actions keys use the current schema; unsupported historical keys receive contextual suggestions | workflow validation and editor-recovery tests |
| DT-01, QA-01 | Invalid creates leave no lease; pagehide releases; contested edits use explicit takeover | editor-recovery browser spec; test_editor_recovery |
| DT-02, FE-02 | Shared keyed reads, independent aborts, StrictMode deduplication and stable effect identities | data-layer browser spec |
| DT-03 | Finished summaries omit log replay and live streams; full job/history reads remain available | monitor-boundaries browser spec; test_web_api |
| DT-04 | Hidden tabs stop polling, unchanged reads back off and focus refreshes | data-layer browser spec |
| DT-05, DE-02 | Compressed builds, vendor/editor/graph chunks, workspace preload and immediate launch shell | data-layer and launch-panel browser specs; static asset tests |
| DT-06 | Three retained frontend generations; development-only hidden maps; wheel excludes maps/build metadata | publish build tests, static asset tests and distribution checker |
| QA-02 | Invalid drafts retain the last valid canvas, saved-source launch, comparison and restore | editor-recovery browser spec; test_editor_recovery |
| QA-03, QA-04 | Located YAML errors, aggregate validation issues and contextual schema suggestions | editor-recovery browser spec; workflow validation tests |
| QA-05 | Inline settings errors, disabled invalid Save and explicit discard | accessibility and settings browser specs |
| QA-06 | Exact approval buttons plus free text, current-attempt validation and deadline provenance | waiting-requests browser spec; human-wait/API tests |
| QA-07 | Inline launch-input errors and focus on the first invalid field | editor-recovery and launch-panel browser specs |
| QA-08, DE-06 | Escape ends welcome, tours start explicitly, successful setup dismisses the banner, reduced motion and reserved loading space | accessibility, onboarding, visual-regression browser specs |
| QA-09, BR-10 | Shared plural rules, consistent home copy and queued durations | dashboard, run-presentation, visual-regression browser specs |
| QA-11, QA-12 | Reserved skeleton geometry, delayed-response CLS checks and reviewed visual baselines | visual-regression browser spec |
| BR-01, BR-07 | Bounded titles/names, full-title dialog, exact text titles and copyable full paths | control-layout, visual-regression browser specs; schema bound tests |
| BR-04 | Jobs-only sidebar/counts, expandable steps with their own output and exit status | actions-layout and visual-regression browser specs |
| BR-11 | Test-only normal/worst-case toggle and isolated stress data | visual-regression browser spec; tests/ui_fixtures.py |
| DE-01, DE-03, DE-04, DE-05, FE-03 | Press feedback, tabular figures, bounded type scale, pointer-aware hover/tooltips and semantic palette/spacing tokens | frontend lint, accessibility and visual-regression browser specs |
| FE-01 | Focused view/controller components with hooks, accessibility, formatting and component-size lint gates | make check-frontend and CI |
| FE-05 | Loading, empty, read-error, success and denied-access states | [State matrix](ui-states.md) and view-states browser spec |

Shell execution continues to use owned private script paths, explicit argument
vectors and `shell=False`. Interpreter-vector tests cover each supported
shell without requiring installed provider accounts. Running each interpreter
on each supported operating system and certifying live provider installations
remain separate platform/certification checks.
