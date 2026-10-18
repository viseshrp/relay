# Relay TODO

Only the coordinating assistant edits this file. Relay workflow agents report
proposed TODO entries without modifying it.

## Agent configuration

- [x] Change the tool, model, effort, and permissions for an unstarted agent
  step while its run is paused. Validate advertised choices, keep captured
  prompts and completed work, and supply editable handoff instructions only
  when the tool/model changes. Saving keeps the run paused. See
  [Monitor and control runs](web-ui.md#monitor-and-control-runs).
- [x] Let the owner hand a failed agent step to another installed tool and exact
  model through Relay. Validate its settings before recovery, clear the previous
  tool's options, preserve the snapshot and completed work, and retain the
  replacement for subsequent retries. Include tool, model, effort, and
  permission choices in Retry with settings. Permit effort and permission
  changes without replacing the model. Show an editable default handoff only
  when the tool/model pair changes, and retain its exact text for later retries.
  Every failed agent step exposes its own settings. Focused API/worker and
  browser checks cover same-tool model changes, ACP/native handoffs, custom
  instructions, multiple failures, idempotency, saved evidence, and quota retries.
- [x] Let the owner retry a failed agent step with a different advertised effort.
  Validate the choice before recovery, keep the original snapshot and earlier
  attempts, and retain the choice for that step's automatic quota retries.
  The run monitor's Retry with settings dialog and the failed-node API now
  support this choice. Focused checks cover default preservation, exact-model
  validation, unchanged snapshots and earlier attempts, idempotency, browser
  execution, and native quota recovery.
- [x] Add an effort dropdown for the selected model. List the effort choices
  supported by that provider and model, and let the user choose. Start with
  **Provider default** selected. Keep the effort override unset unless the user
  selects another value.
- [x] Add a permission-mode dropdown for each agent tool. List the modes
  supported by that provider and tool, and let the user choose. Start with
  **Provider default** selected. Keep the permission-mode override unset unless
  the user selects another value.

Implemented in the workflow editor with per-tool overrides, fresh capability
discovery, launch validation, and worker configuration. Tests cover provider
defaults, explicit choices, model changes, save and reload, and execution.

Tools that expose no separate effort selector retain Provider default.
Antigravity includes effort in its exact model slug; choose another exact model
to change that effort.

## Guided app experience

- [x] Make owner login optional for a local installation. Keep login required
  by default, support `relay up --no-login` and the saved `login_required`
  setting, and open the browser app directly when disabled. Preserve owner
  credentials, CSRF and host checks, live updates, and run attribution.

- [x] Make Relay intuitive for first-time users. Guide them through choosing a
  project and workflow, starting work, reviewing requests, and resuming a run.
  Use everyday language and clear next actions so common tasks do not require
  understanding YAML, internal node names, JSON, or status codes.
- [x] Keep advanced configuration and diagnostics in clearly labeled optional
  views. Explain what actions do and what happens next before starting,
  stopping, or approving work. Preserve explicit human review and permission
  decisions.
- [x] Make long workflows easy to navigate in the authoring canvas.
  Loading another workflow starts at its first stage with fresh positions
  and readable zoom. A searchable stage list supports keyboard selection and
  repeated centering after panning. Browser checks cover workflow changes,
  narrow layouts, unchanged saved sources, and unsaved-instruction protection.

## Run navigation

- [x] Configure fix-and-verify repair rules on a stage. Relay runs rejected
  verdicts through the selected fixer and verifier, preserves each report,
  and stops when the configured budget is exhausted. Keep repair work out of
  the main map and expose its settings and attempts in a Repairs panel.
  Existing captured loops can be explicitly grouped without changing their
  execution. See [Stage repair rules](workflows.md#stage-repair-rules).
- [x] Pause new steps without interrupting the currently running agent. Show
  the hold in the run monitor, preserve it across restart, and let the owner
  change unstarted-step settings before explicitly resuming. Queued deliveries
  and automatic recovery respect the durable hold. See
  [Pause new steps](execution.md#pause-new-steps-and-change-an-unstarted-agent).
- [x] Explain the workflow editor and run monitor in the navigation. Show the
  selected project, workflow, and run together so the owner can identify the
  work being inspected.
- [x] Show the current stage, completed work, and next action in plain language
  above the graph and logs. Make waiting and failed stages easy to find without
  reading internal node names or zooming around the graph.
  Show stopped step, Show step, and stage buttons bring the graph into view
  and focus the chosen step. Repeated clicks restore its readable scale.
- [x] Draw dependency and control-flow connections in the run monitor using
  the run's captured workflow and runtime scopes. Arrange nodes by their
  connections so branches, nested scopes, and stage order are readable.
- [x] At a human review gate, show the review documents or diff, the required
  review steps, and the expected response beside the response field. Keep human
  approval distinct from automated checks and agent permission requests.
- [x] Provide links to a specific run and its pending interaction. Preserve
  that selection across reloads so opening the app returns to the intended
  stage instead of the default workflow editor.

## Run output

- [x] Join streamed agent text and command output into readable messages or
  lines instead of a separate card for every fragment. Preserve ordering and
  boundaries between nodes, attempts, messages, and output streams, and show
  which node and agent produced the output.
- [x] Show readable messages and tool summaries by default. Keep raw provider
  JSON and low-level events in an optional diagnostics view, with the original
  events available for inspection. Make ongoing output readable without
  opening a full-text dialog for each fragment.

## Workflow handoffs

- [x] Reprompt the assigned agent after an eligible failure through an opt-in
  recovery policy. Preserve failed reports and successful report handoffs,
  append a bounded repair instruction separately from the captured prompts,
  and keep the provider, model, effort, and permissions unchanged. Allow at
  most two additional attempts per step, preserving that budget across
  restarts and repeated failures. Unsafe failures and exhausted retries stop
  visibly. The editor and run monitor expose recovery controls, progress,
  blockers, and the exact instruction. Focused provider, API, engine, and
  browser checks cover report recovery, idempotency, cancellation, nested
  scopes, quota schedules, unchanged snapshots, and live updates. See
  [Automatic step recovery](execution.md#automatic-step-recovery).
- [x] Show the failed step, failure description or exit code, and the provider's
  last public message at the top of the run. Keep quota notices and reported
  reset times visible after reload, without replaying the entire activity log.
- [x] Recognize structured provider usage limits and preserve the failed step
  for an automatic resume after the reset without changing its model or
  reasoning effort. Claude's typed rejection and confirmed reset now create a
  durable schedule in Relay. Missing or stale resets remain visibly blocked;
  cancellation removes the schedule. No reset times are guessed. See
  [Provider usage resets](execution.md#provider-usage-resets).
- [x] Restore supervision when a lost supervisor leaves its web or worker
  children running. Verify ownership and protect against reused process IDs
  before stopping or reusing children. Preserve completed runs and avoid
  requiring manual process inspection and signaling to restart Relay.
  A lifetime kernel lock and atomic creation-identity record now authorize
  takeover only after the recorded owner exits. Matching children stop before
  restart reconciliation; reused or unverifiable PIDs remain untouched. See
  [Restart after a lost supervisor](execution.md#restart-after-a-lost-supervisor).

- [x] Create and save new workflows through Relay without manually adding a
  bootstrap YAML file. Keep prompts and agent execution bound to the selected
  project and stop downstream stages automatically when that binding is wrong.
- [x] Handle generated planning and review documents without requiring manual
  Git exclusions before launch. Preserve existing documents and keep them
  unstaged and uncommitted unless the owner explicitly requests otherwise.
- [x] Warn when required report handoffs use only `exists` outputs. Relay
  already retains files declared with `label`, `json_path`, or `yaml_path`.
  Guide workflow authors to those selectors and automatic verdict checks,
  while preserving actual human review and approval gates.
- [x] Accept owner feedback while an agent is paused and resume it through
  Relay, without manually editing prompt files or restarting a worker.
- [x] Clean up run-owned temporary files, browser profiles, and processes
  through Relay after the run finishes. Preserve personal browser sessions,
  credentials, unrelated files, and the owner's existing Relay data.
- [x] Select one terminal run for confirmed cleanup through the API. Preserve
  earlier runs, shared logs, and retained reports when removing a checkout.
  Reject missing, malformed, and foreign run selections without broadening
  deletion, and serialize selected cleanup with recovery. Focused API checks
  cover these boundaries and incomplete evidence.

The [web guide](web-ui.md) covers project selection, workflow creation, run
progress, report previews, explicit review decisions, and readable activity.
[Workflows](workflows.md) and [Git and artifacts](git-and-artifacts.md) describe
source capture and generated-document handling.
[Agents](agents.md) explains feedback in a live ACP session; native Antigravity
keeps its single-turn headless transport.
[Projects and storage](projects-and-storage.md) defines temporary-resource
ownership and cleanup boundaries. The [HTTP API](http-api.md) documents the
matching endpoints, project binding, and interaction links.

Focused Python checks and browser scenarios cover creation without a bootstrap,
captured connections, report handoffs, explicit approval, reload links,
same-session feedback, and cleanup that preserves unrelated files and processes.

## Beginner experience and GitHub Actions familiarity

New users leave because Relay asks them to learn Relay before they get value.
The product promise is "GitHub Actions, but you can draw and edit the workflow
in the browser." Today the app looks and behaves like an internal operations
console instead. This section is the product backlog that closes that gap.

The findings come from a full walkthrough of the running app on 2026-10-06
(Runs, Workflows, every panel and dialog that opens without starting or
changing work, 1440 px and 900 px widths), the CLI source, the frontend
source, and the docs. Nothing was launched, retried, saved, or cleaned during
the audit. Items marked **Contract change** alter a runtime rule in
[AGENTS.md](../AGENTS.md) and need explicit owner approval before
implementation.

The jobs-and-steps contract is in [Workflows](workflows.md). The
[implementation index](backlog-implementation.md) maps the findings to their
implementations and proving tests.

### Product principles

1. **GitHub Actions is the reference.** Where GitHub Actions has a word, layout,
   icon, or behavior for the same idea, Relay uses it unless that would be
   unsafe. A user who has opened the Actions tab should know where to click.
2. **The browser can do everything the YAML can.** Every workflow field has a
   form control. YAML stays fully editable, side by side and in sync.
3. **First value in five minutes.** Install, open, pick a starter, run, see a
   result, without reading docs.
4. **Plain words first, details on demand.** Internal IDs, hashes, scope paths,
   provider option slugs, and raw JSON appear only under "Details".
5. **One obvious next action.** Every screen states what is happening and the
   single thing the user should do next, in the same place every time.

### Vocabulary map

Use these names in the UI, docs, and CLI output. Keep YAML keys unchanged
unless an item below says otherwise.

| GitHub Actions | Relay today | Relay target UI name |
| --- | --- | --- |
| Actions tab | Runs tab | **Actions** (or keep **Runs**, see BX-03) |
| Workflow | Workflow | Workflow |
| Job (`jobs.<id>`, with `needs`) | Stage / step / node (mixed) | **Job** |
| Step inside a job | Prompt, command argv | **Step** (the agent prompt or command) |
| `runs-on` | `agents`, model, effort | **Runs on** (agent + model) |
| Run workflow (`workflow_dispatch`) | Start work / Launch workflow | **Run workflow** |
| Re-run all jobs / Re-run failed jobs | Retry step (failed only) | **Re-run all jobs** / **Re-run failed jobs** |
| Cancel workflow | Stop work | **Cancel run** |
| Environment approval / required reviewers | Human wait / human review | **Approval** |
| Artifacts | Saved files / artifacts | **Artifacts** |
| Summary graph | Steps and progress + map | **Summary** graph |
| `if`, `needs`, `${{ }}`, `inputs`, `env` | Same keys | Same keys (already familiar) |
| `timeout-minutes` | `timeout: 5m` | **Timeout** |

### P0: attrition blockers

- [x] **BX-01. Add a first-run setup screen.**
  - **What:** The first screen a new user sees after `relay up`.
  - **Problem:** With login on, the first screen is an account form that says
    "Create the only owner account for this installation" and mentions
    "Django's local password checks". With login off, the user lands directly
    in an editor or run view with no explanation of what Relay is. Agent
    readiness exists only as one-line JSON from `relay doctor`; the browser
    never tells the user whether Codex, Claude Code, Copilot, Cursor, or
    Antigravity is installed and signed in. `/api/agents` already exists but
    no screen shows it. A user with no working agent can author a workflow,
    press Launch, and only then learn that nothing can run it.
  - **Change:** Add a **Get started** checklist that appears until it is
    complete and stays reachable from a help menu:
    1. Project: shows the current Git repository, or a folder picker
       (BX-24).
    2. Agents: one card per supported agent with **Ready**, **Installed, not
       signed in**, or **Not installed**, the exact fix (install link, sign-in
       command to copy), and **Check again**. Reuse the doctor probe.
    3. First workflow: **Start from a template** (BX-02) or **Blank
       workflow**.
    4. First run: **Run workflow** with the template's sample input.
    Rewrite the account form copy: "Create a password for this computer's
    Relay. Only people who can use this computer can reach it." Show
    password rules before submit, never mention Django.
  - **Outcome:** A new user knows within one screen what Relay does, whether
    their agents work, and what to click next.
  - **Done when:** A fresh install with one ready agent reaches a successful
    template run without typing a path, editing YAML, or opening docs.
    Browser tests cover zero, one, and all agents ready, and login on/off.

  The web UI's Get started section and HTTP readiness reference document the
  checklist. `get-started.spec.ts`, `optional-login.spec.ts`, and
  `tests/test_web_api.py` cover onboarding, readiness, and the first run.

- [x] **BX-02. Ship starter workflow templates. Contract change.**
  - **What:** Ready-made workflows a user can pick instead of a blank file.
  - **Problem:** A blank workflow and empty prompt provide no example to
    edit. **New workflow** asks only for a name. A
    beginner faces an empty canvas and a schema they have never seen.
    GitHub Actions solves this with "Choose a workflow" starter cards; Relay
    has none. [AGENTS.md](../AGENTS.md) forbids bundled templates "without an
    explicit product request"; this item is that request and needs owner
    sign-off.
  - **Change:** Add a **Choose a workflow** gallery to **New workflow** and
    the setup screen. Ship 5 to 8 small templates, each with a one-line
    purpose, a graph preview, its required agents, and typed inputs:
    - Ask an agent (one agent job, one `task` input).
    - Plan, approve, implement (agent → approval → agent).
    - Implement and test (agent → command `npm test` / `pytest`).
    - Review my branch (read-only agent writing `REVIEW.md` with a
      `Ready:` label).
    - Fix until tests pass (agent + test command + repair rule).
    - Write docs for a change.
    Templates copy into `.relay/workflows/` and `.relay/prompts/` on choice;
    Relay never runs a template in place. Templates use only documented
    fields and pass `scripts/check_workflow_examples.py`.
  - **Outcome:** The first workflow is a working example the user edits, not
    a blank page.
  - **Done when:** Each template validates, launches against the fake agent
    in browser tests, and is copied byte-exactly. Docs list the templates.

  The workflow guide's Starter workflows section lists the six approved
  bundles. `tests/test_workflow_starters.py` covers byte copies, conflicts,
  rollback, and bounded repairs; browser tests launch every starter.

- [x] **BX-03. Reorganize navigation to match the GitHub Actions tab.**
  - **What:** The app's top-level layout.
  - **Problem:** The app has two tabs, **Workflows** (editor) and **Runs**
    (history + monitor). Runs are not grouped by workflow, so a project with
    many workflows shows one flat
    list of similar names ("Inspect site handoff bd8b921c" three times,
    "Selected tabs" twice). The workflow list is a dropdown inside the
    editor. There is no page that answers "what workflows do I have and how
    did each last run?" GitHub Actions answers this on one screen.
  - **Change:** Use the GitHub Actions layout:
    - Left sidebar: **All workflows**, then each workflow by name with its
      last-run status icon, plus **New workflow**.
    - Main area for a workflow: header with name, file path, **Run
      workflow** (BX-06), and **Edit**; below it the run list (BX-14).
    - Run page (BX-04) and editor (BX-07) open from there and have
      breadcrumbs: Project › Workflow › Run #12.
    - Use the `workflows` URL view.
  - **Outcome:** Users find workflows, runs, and the editor where GitHub
    Actions trained them to look.
  - **Done when:** A user can go from the workflow list to a run, to a job,
    to its log, and back, using only the sidebar and breadcrumbs.

- [x] **BX-04. Give every job a log view, like a GitHub Actions job page.**
  - **What:** The run page's main reading surface.
  - **Problem:** A run page today stacks, in one long scroll: a status card,
    **Unstarted agent steps**, a wall of 29+ "Name · Status" chips, a graph,
    a collapsed **Repairs** panel, one mixed **Activity** feed for every job,
    a review panel, diagnostics, and data cleanup. Clicking a chip or node
    only centers the graph; it does not show that job's output. A failed
    command says "The tool exited with code 1. Open the step's activity for
    its output", but there is no per-step activity: in the observed failed
    run ("Verify size caps"), the visible feed contained only the previous
    job's tool calls, and the failing command's stderr was hidden behind
    repeated **Load more activity**. This is the single biggest gap versus
    GitHub Actions, where you click the red job and the failing step is
    already expanded.
  - **Change:**
    - Run page layout: left column lists jobs with status icons and
      durations (grouped by loop iteration and repair round); right column
      shows the **Summary** (graph + status + approvals + artifacts) or the
      selected job.
    - Job view: header (job name, runs-on agent and model, attempt picker,
      duration, **Re-run job**), then collapsible sections: **Set up**,
      **Instructions** (prompt files, read-only), **Agent conversation** or
      **Command output**, **Outputs** (declared values), **Changes**
      (commits by this job), **Complete**. Failed jobs open with the
      failing section expanded and scrolled to the error.
    - Command output is a monospace terminal view with line numbers,
      stdout/stderr marking, ANSI color, and copy/download buttons.
    - Selecting a job in the graph, list, chip, or a failure notice opens
      this view and updates the URL (`&job=<scope path>`).
  - **Outcome:** "Why did it fail?" takes one click.
  - **Done when:** For any failed command or agent job, the error text is
    visible without scrolling or paging after one click. Browser tests cover
    commands, agents, loops, nested workflows, and multiple attempts.

  Implemented in the Run monitoring section of `docs/web-ui.md` and the
  Job history section of `docs/http-api.md`. `tests/test_web_api.py` and
  `frontend/e2e/job-history.spec.ts` cover attempts, captured instructions,
  bounded reads, privacy, errors, loops, nested jobs, and output downloads.

- [x] **BX-05. Make "needs your input" impossible to miss.**
  - **What:** How approvals, agent questions, and permission requests reach
    the user.
  - **Problem:** In the observed paused run, the only place that said **Needs
    your input** was a line deep inside the collapsed **Repairs** panel
    ("Repairs (iteration 1) · Needs your input"). The header said "New steps
    are paused", the run list said "New steps paused", and no response form
    was on the page. The review panel at the bottom said "Follow the review
    instructions before sending your response" although no response field
    existed. Users cannot tell whether Relay is waiting for them.
  - **Change:**
    - One rule: when any attempt has a pending interaction, the run header
      shows a yellow **Waiting for you** banner with the question and a
      **Respond** button that opens the form in place.
    - The Runs/Actions nav item and the browser tab title show a count
      (e.g. "(1) Relay"). The run list shows a waiting icon.
    - Optional desktop notification (opt-in) for waiting and finished runs.
    - Paused, waiting, and failed are distinct states with distinct icons and
      copy; never show "Needs your input" unless a respondable form exists.
    - The review panel shows "Respond" copy only when a review is pending;
      otherwise title it **Changes and documents**.
  - **Outcome:** A user glancing at any screen knows whether Relay is waiting
    for them and gets to the form in one click.
  - **Done when:** Every interaction kind (human wait, permission,
    elicitation, nested in loops/subworkflows/repairs) surfaces in the
    header, nav count, and run list. A test asserts that no "needs input"
    label renders without an actionable form.

  Implemented in Monitor and control runs in `docs/web-ui.md` and the
  attention read in `docs/http-api.md`. `tests/test_web_api.py`,
  `frontend/e2e/waiting-requests.spec.ts`, and the pause browser regression
  cover all request kinds, nested scopes, counts, focus, and notifications.

- [x] **BX-06. Put "Run workflow" at the top, like `workflow_dispatch`.**
  - **What:** The launch control.
  - **Problem:** **Start work** sits at the very bottom of the editor page,
    below the canvas, the YAML panel, and the selected stage's settings. On
    a long workflow the user scrolls past a full prompt to find **Launch
    workflow**. It is disabled for unsaved changes without saying why at the
    point of the button. Inputs show only a label (`Task *`), no
    description. **Advanced start settings** shows "Exact model (optional)",
    "Cleanup policy: Clean on success", and an empty "Entry point" select
    with no explanation.
  - **Change:**
    - A primary **Run workflow** button in the workflow header and on the
      workflow's run list opens a compact panel (GitHub's dropdown pattern):
      branch shown read-only ("runs on a new branch from `main`"), typed
      inputs with their `description`, defaults prefilled, multi-line text
      for long strings, and **Run workflow**.
    - If launch is blocked, the panel says exactly why and how to fix it:
      "Save your changes first" with a Save button; "2 uncommitted files
      block the run" with the list (BX-27).
    - Advanced options are renamed and explained: "Override model for this
      run", "After a successful run: delete the working copy / keep it",
      "Start from job" (entry point) with the job list.
  - **Outcome:** Running a workflow is one obvious button with a short form.
  - **Done when:** Launch is reachable without scrolling from the workflow
    page and the editor. All disabled states state their reason.

  The web UI guide's Launch a run section covers the header panel, inputs,
  Save blockers, and run options. `frontend/e2e/launch-panel.spec.ts` checks
  launch, types, failures, history navigation, and focus; project and API
  tests cover fresh branch previews without changing Git state.

- [x] **BX-07. Make every YAML field editable in the browser.**
  - **What:** The stage (job) settings panel and workflow settings.
  - **Problem:** Incomplete forms force users into YAML for outputs,
    conditions, timeouts, prompts, environment values, workflow inputs,
    reusable workflows, and loop bodies.
  - **Change:** Add form controls for every field in
    [Workflows](workflows.md), grouped in tabs in the job panel:
    **General** (name, needs, if, timeout), **Agent** (agent,
    model, effort, permissions), **Steps** (prompts or command), **Outputs**
    (selector builder: file + label / JSON path / YAML path / exists, with a
    "retained report" explanation), **Environment** (key/value table),
    **When it fails** (BX-23). Add a **Workflow settings** dialog with an
    **Inputs** table editor (name, type, required, default, description,
    constraints) and defaults. Expose built-in actions through **Add step**.
    Draw loop bodies as an expandable group on the canvas, and reusable
    workflows as a linked card that opens the child file.
  - **Outcome:** A user never has to open YAML to express anything Relay
    supports.
  - **Done when:** For each field in the schema, a test edits it through the
    form and asserts the exact YAML, and the reverse (YAML edit updates the
    form). The canonical round-trip rules still hold.

- [x] **BX-08. Let commands be scripts. Contract change.**
  - **What:** How a command job's program is written.
  - **Problem:** Commands must be an argument vector with no shell, so a
    GitHub Actions user's `run: npm test` is invalid ("A scalar command is
    invalid"). Real workflows in this project work around it with long
    `uv run --no-project python -u -c "..."` one-liners that embed escaped
    multi-line Python inside a JSON array; in the form, that becomes a
    single unreadable "argument" line. This is the most visible difference
    from GitHub Actions and it pushes users toward unreadable workflows.
  - **Change (needs approval because it touches the `shell=False` rule):**
    - Allow `run:` as a string with an explicit or default `shell:`
      (`bash`, `sh`, `pwsh`, `python`), like GitHub Actions. Relay executes
      it as an argument vector, for example
      `[bash, -e, -o, pipefail, -c, SCRIPT]` or `[python, -c, SCRIPT]`,
      still with `shell=False` at the subprocess layer and the same
      process-group ownership. The default shell is `bash` on macOS and
      Linux and `pwsh` on Windows, as in GitHub Actions.
    - Use `relay/command@v1` for exact argument vectors.
    - The form offers **Script** (multi-line code editor with syntax
      highlighting for the chosen shell) or **Program and arguments**.
    - Preview shows the exact process arguments Relay will run.
  - **Outcome:** `run: npm test` and multi-line scripts work as GitHub
    Actions users expect.
  - **Done when:** Security review signs off; tests cover each shell on each
    OS, exit codes, quoting, and cancellation; docs and the example checker
    cover both forms.

- [x] **BX-09. Make the CLI readable by people.**
  - **What:** `relay init`, `relay doctor`, `relay project`, `relay data`,
    and all CLI errors.
  - **Problem:** `relay doctor`, `relay project list`, `relay project
    relink`, and `relay data clean` print one long line of sorted JSON.
    Every error prints a JSON envelope such as
    `{"code": "config_error", "context": {}, "message": "Bad host."}`.
    The README's quick start is `relay init`, `relay doctor`, `relay up`,
    but `doctor` checks Git with the raw porcelain status
    (`relay/cli.py` doctor → `status_porcelain`), so the untracked
    `.relay/` files that `init` just created appear to make the `git` check
    fail with `git_dirty` and exit code 6, even though launch exempts
    them. (Found by reading the code; confirm with a disposable repository.)
    There is no `relay open` to reopen the browser, and `relay up` gives no
    hint about what to do next.
  - **Change:**
    - Default to human output: a short checklist with ✓/✗, the reason, and
      the exact fix command per failed check. Add `--json` for
      machine-readable output.
    - Errors print `Error: <message>` plus `Next: <next_action>`; `--json`
      keeps the envelope.
    - `doctor` uses the same launch cleanliness rules as the server, and
      reports dirty files as a warning with the file list, not a failure,
      when launch would still be allowed.
    - `relay up` prints the URL, whether login is on, how to stop, and
      "Open the URL above to create your first workflow".
    - Optional: let `relay up` run `init` when `.relay/` is missing
      (prompting first), so the quick start is one command.
  - **Outcome:** A beginner can run the quick start and understand every
    line of output.
  - **Done when:** CLI tests snapshot human and `--json` output; quick start
    in a fresh repo passes `doctor`.

  The README command reference and launch-cleanliness notes document readable
  output and `--json`. `tests/test_cli_config.py` covers exact output, isolated
  initialization, allowed reports, blocked code and staged files, and startup.

- [x] **BX-10. Replace the two-save model with one Save.**
  - **What:** Saving instructions and saving the workflow.
  - **Problem:** Agent instructions have their own **Save instructions**
    button, then show "Instructions saved. Save the workflow to include them
    in the next run." The workflow has a separate **Save**. Unsaved
    instructions block switching stages, projects, saving, and launch. Users
    must learn two save states, a lease, and a draft concept.
  - **Change:** One **Save** (and Cmd/Ctrl+S) writes the workflow and every
    changed prompt file together, with one validation result. Show a single
    "Unsaved changes" indicator listing what changed. Allow switching jobs
    with unsaved edits (keep them in the draft). Offer **Discard changes**.
  - **Outcome:** Saving works like every other editor.
  - **Done when:** Prompt and workflow edits save atomically, conflicts are
    reported once, and navigation never blocks on unsaved instructions.

### P1: clarity and familiarity

- [x] **BX-11. Make Activity readable.**
  - **What:** The agent and command output feed.
  - **Problem:** Agent Markdown is shown raw (`**Stopping pending
    clarification**` with literal asterisks). Every tool use is two cards,
    "Tool call · in_progress" and "Tool result · completed", both repeating
    the full command or absolute path, for example
    `/private/tmp/relay-suspendit-…/worktrees/3af601f0-…/WALKTHROUGH.md`.
    "Thought" cards show private-looking headings. The feed is a scroll box
    inside the scrolling page, defaults to the newest page, and has both
    **Show earlier messages** and **Load more activity**. There is no filter
    by job, no search, and no follow-tail toggle.
  - **Change:** Render Markdown safely (no raw HTML). Merge each tool call and
    its result into one row with a status icon, a short title ("Read
    WALKTHROUGH.md", "Ran `git status`"), and an expandable body. Show paths
    relative to the worktree. Collapse thoughts by default. Live view
    follows the tail until the user scrolls up, then shows **Jump to
    latest**. Add filter by job and text search. Use the page's scroll, not
    a nested one, inside the job view (BX-04).
  - **Outcome:** Output reads like a chat transcript and a terminal log.
  - **Done when:** Markdown, merged tool rows, relative paths, filters, and
    tail-follow are covered by unit and browser tests; raw events stay
    under Details.

  The web UI guide's run-monitor section covers safe Markdown, merged tool
  rows, filters, and page scrolling. Activity-feed and presentation tests
  cover matching boundaries, path handling, inert HTML, live following,
  paging failures, and raw Details; job API tests cover recorded folder data.

- [x] **BX-12. Make the run graph readable and stop it stealing the scroll.**
  - **What:** The graph on the run page and the editor canvas.
  - **Problem:** At default zoom on a 29-job run, node labels are a few
    pixels tall and unreadable. Scrolling the page with a mouse wheel over
    the graph zooms the graph instead, trapping the user mid-page. Nodes show
    only a name and a status word; there is no type icon, duration, agent, or
    model. Helper jobs ("Explore artifacts", "Planning exhausted",
    "Iteration limit" ×4, "Child steps") clutter the map. The minimap covers
    nodes at 900 px width. The read-only run graph's accessibility text says
    "press delete to remove it".
  - **Change:** Use GitHub-style job cards (status icon, name, duration,
    agent/model chip) at a fixed readable size; lay out left-to-right like
    the Actions summary graph. Wheel scrolls the page; zoom uses Ctrl/Cmd +
    wheel, pinch, or the buttons. Hide the minimap below 1200 px and by
    default on small graphs. Collapse helper and exhausted-route jobs into
    their parent with a "+3 checks" affordance. Remove edit hints from the
    read-only graph.
  - **Outcome:** The graph is a glanceable summary, as in GitHub Actions.
  - **Done when:** A 30-job run is readable at its initial fit on a 1440 px
    screen, and page scrolling over the graph scrolls the page.

- [x] **BX-13. Replace the chip wall with a job list.**
  - **What:** The **Steps and progress** block.
  - **Problem:** It renders every job as a "Name · Status" text chip in a
    wrapping block with its own scrollbar, then repeats the same list as
    graph nodes. Iteration jobs ("Revise (iteration 1)") mix with root jobs.
    Status is text only.
  - **Change:** Remove the chip block. The run page's left job list (BX-04)
    shows status icons, durations, and indentation for loop iterations,
    repairs, and subworkflows, with failed and waiting jobs pinned to the
    top.
  - **Outcome:** One list, one graph, no duplication.
  - **Done when:** Every job appears once in the list, grouped correctly.

  The web UI guide's run-monitor section covers the single indented job list
  and pinned waiting or failed jobs. Job-history and repair browser tests
  compare recorded scopes with visible rows, check nesting and keyboard
  navigation, and cover duplicate and partial pages in the ordering helper.

- [x] **BX-14. Upgrade the run list to GitHub's run list.**
  - **What:** **Run history**.
  - **Problem:** Each row shows only the workflow display name, a status
    word, and a start timestamp. No run number, duration, task input, branch,
    commit, or who started it. Status words vary ("Needs attention",
    "Stopped", "Complete", "New steps paused"). No filters or search. Many
    rows share the same name.
  - **Change:** Each row: status icon, **#number**, run title (first line of
    the main input, e.g. the task, falling back to the workflow name),
    workflow name, branch, duration, relative start time ("12 min ago" with
    exact time on hover). Filters: status, workflow; text search. Paginate.
    Highlight waiting runs.
  - **Outcome:** Users find a run by what it was for.
  - **Done when:** Runs show numbers and titles; filters work with links.

- [x] **BX-15. Make artifacts understandable.**
  - **What:** **Advanced diagnostics and saved files**.
  - **Problem:** Artifacts are listed by internal name with the SHA-256 hash
    as the main subtitle and no job attribution. The observed run listed
    about 25 `commits` and `worktree_diff` entries of `0 bytes`, with real
    documents (`review`, `walkthrough`, `draft_plan`) buried among them.
    The event list shows raw `run.created`/`node.created` JSON. Everything
    is under one "Advanced" label.
  - **Change:** Add a top-level **Artifacts** section (GitHub's name) listing
    declared reports and files with job name, size, and **Preview** /
    **Download**; add **Download all**. Hide empty internal records. Move
    hashes, events, branch names, and resource cleanup into **Details**.
  - **Outcome:** The documents the workflow produced are easy to open.
  - **Done when:** Empty internal records never appear in the main list;
    each artifact names its job.

- [x] **BX-16. Make data cleanup safe and explain it.**
  - **What:** **Advanced data cleanup** on every run page.
  - **Problem:** The scope select defaults to **Everything**, sitting next to
    a red **Clean data** button at the bottom of every run page, including
    the one being watched. The only text is "Cleanup is rejected while any
    project run is active and always requires confirmation." There is no
    description of what each scope deletes or how much.
  - **Change:** Move cleanup to a project **Settings › Storage** page. Show
    each category with its size and count and a plain explanation
    ("Working copies: folders Relay used to run jobs. Your repository is not
    touched."). No default selection. The confirmation names counts and
    asks the user to type the project name for **Everything**.
  - **Outcome:** Nobody deletes run history by accident.
  - **Done when:** The run page has no cleanup controls; settings show sizes.

  The Settings and cleanup sections in `docs/web-ui.md` and the run-owned
  resources section in `docs/projects-and-storage.md` describe the controls.
  `frontend/e2e/settings.spec.ts`, `frontend/e2e/storage.spec.ts`, and
  `tests/test_web_api.py` cover counts, confirmation, cleanup, and safety.

- [x] **BX-17. Use one status vocabulary and color system.**
  - **What:** Status words, icons, and colors across the app.
  - **Problem:** Observed labels include Complete, Skipped, Not started,
    Repairing, Starting, Needs attention, Needs your input, Stopped, Repairs
    paused, New steps paused, Ready to edit. **Ready to edit** rendered
    orange on first load and green later. YAML strings are red, which reads
    as errors.
  - **Change:** Adopt GitHub's set: **Queued** (grey dot), **In progress**
    (yellow spinner), **Waiting** (orange clock, for approvals and input),
    **Paused** (grey pause), **Success** (green check), **Failure** (red
    cross), **Cancelled** (grey slash), **Skipped** (grey dash). Map every
    backend state to one of these with an optional detail line
    ("Repairing, round 1 of 4"). Use a neutral editor theme for YAML. Use
    color only with an icon and text.
  - **Outcome:** Status reads the same everywhere and matches GitHub.
  - **Done when:** A single mapping module drives list, graph, header, and
    job views; tests cover every backend state.

- [x] **BX-18. Remove jargon from the default view.**
  - **What:** Copy across the app.
  - **Problem:** Default views show internal terms: "Provider default",
    "Effort override: ultra", "Permission override: agent-full-access",
    "Keep current permission mode (auto_approve)", "Owner input required",
    "Workflow key", "Entry point", "Cleanup policy", "Exact model override",
    "Scope", "SSE live", "Captured workflow model", "Child steps", "Load
    available models".
  - **Change:** Rewrite with a glossary owned by the frontend, for example:
    Provider default → "Agent's default"; Effort → "Thinking effort";
    Permission mode → "What the agent may do", with each option's provider
    description shown; Owner → "you"; Workflow key → "File"; Entry point →
    "Start from job". Add a small "?" tooltip next to each advanced field
    that links to the matching doc section.
  - **Outcome:** A new user understands every label on the default view.
  - **Done when:** A copy review lists every visible string; none of the
    terms above appear outside Details.

- [x] **BX-19. Fix model names and simplify model choice.**
  - **What:** Model display and selection in the job panel and dialogs.
  - **Problem:** The model menu shows `gpt-6-astra` as **6 Astra**, losing
    the vendor prefix. The unstarted-steps list shows slugs
    (`gemini-3.8-flash-high`) while the dialog shows labels ("Gemini 3.8
    Flash (High)"). The panel has a **Model** menu, an **Exact model
    override** text field, and a **Load available models** link that do
    overlapping things.
  - **Change:** One searchable combobox per job: label first, exact value in
    smaller text, provider defaults labeled, a **Refresh** icon inside it,
    and "Use a model not in the list" as a final option that reveals the
    exact-value field. Show "label (value)" consistently everywhere. Fix the
    label derivation that drops the `gpt-` prefix.
  - **Outcome:** Users pick a model once, and see the same name everywhere.
  - **Done when:** Label rendering is unit tested against all provider
    fixtures; exact-value rules are unchanged.

- [x] **BX-20. Improve the instructions editor.**
  - **What:** **Instructions for this agent**.
  - **Problem:** A plain textarea with placeholder "What should the agent
    do?" holds a long Markdown prompt. It does not show which file it edits,
    has no preview, and supports only one prompt file per agent in the form.
    Upstream outputs and inputs are delivered as separate context, but the
    editor never tells the user what the agent will receive.
  - **Change:** Use the CodeMirror Markdown mode with a **Preview** toggle.
    Show the file path (`.relay/prompts/explore.md`) with **Rename** and
    **Use an existing prompt**. Support ordered multiple prompts (local and
    global) with drag-to-reorder. Add a **What the agent receives** panel
    listing inputs, upstream outputs, and run metadata for this job.
  - **Outcome:** Writing instructions feels like editing a README.
  - **Done when:** Prompt files can be created, reused, reordered, and
    previewed in the browser.

- [x] **BX-21. Put the canvas and YAML side by side with a GitHub-quality
  editor.**
  - **What:** **Advanced workflow settings and YAML**.
  - **Problem:** YAML is hidden in a collapsed panel under the canvas, next
    to a free-text "Workflow key" field with a **Load** button. The observed
    workflow is stored in JSON flow style, with embedded escaped Python on a
    single line, so the "YAML" view reads as minified JSON. There is no
    schema-aware completion, hover help, or inline error that points to a
    job.
  - **Change:** Editor layout with three switchable modes: **Visual**,
    **YAML**, **Split** (default on wide screens). Add JSON Schema-driven
    completion and hover docs, errors underlined at the exact key with a
    link to the job in the visual view, and a **Format as YAML** command
    that rewrites flow style into block style and long strings into
    literal blocks (`|`), with a diff preview before saving. Replace the
    workflow key field with the workflow sidebar (BX-03).
  - **Outcome:** YAML editing is as comfortable as GitHub's workflow editor.
  - **Done when:** Split view stays in sync both ways; schema completion
    covers every key; formatting preserves values and comments where the
    parser allows.

- [x] **BX-22. Make the canvas a real drawing tool.**
  - **What:** Building workflows visually.
  - **Problem:** Nodes are plain rectangles with a name. Dependencies change
    only through a **Start after** select in the panel. There is no
    drag-to-connect, no "+" to insert a job, no right-click menu, no
    duplicate, and no undo. The selected job is centered but may be cut off
    at narrow widths. The panel opens below the canvas, so the user scrolls
    between the drawing and its settings.
  - **Change:** Drag from a node handle to another node to add `needs`;
    select an edge and press Delete to remove it. Hover "+" between nodes
    inserts a job. Right-click: Duplicate, Delete, Run from here (entry
    point). Undo/redo (Cmd/Ctrl+Z). Node cards show a type icon and key
    info (agent + model, or command). Open settings in a right-side drawer
    next to the canvas.
  - **Outcome:** Users can draw a workflow without touching forms first.
  - **Done when:** Each gesture rewrites the same YAML document and is
    covered by browser tests, including undo.

- [x] **BX-23. Consolidate failure handling into "When this job fails".**
  - **What:** Automatic recovery, repairs, retry with settings, and quota
    retries.
  - **Problem:** Four overlapping recovery features appear in different
    places: an **Automatic recovery** toggle in Start work and on the run
    page, **Allow automatic retries for this step** in the job panel, a
    **Repairs** dialog per stage, a **Repairs** panel on runs, and **Retry
    with settings**. The editor also shows a loop stage literally named
    "Repairs" next to the **Repairs** button. Beginners cannot tell which
    to use.
  - **Change:** One **When this job fails** tab per job with plain choices:
    "Stop and tell me" (default), "Retry up to N times", "Ask a fixer agent
    and re-check" (repair rule). Workflow-level recovery becomes the default
    for new jobs in **Workflow settings**. The run page shows recovery
    activity inside the job view (BX-04).
  - **Outcome:** One place, one decision.
  - **Done when:** Existing YAML (`recovery`, `auto_retry`, `repairs`) maps to
    the new tab without changing semantics.

- [x] **BX-24. Make opening a project easy.**
  - **What:** **Open another project**.
  - **Problem:** The dialog says "Choose a Git repository" but offers only a
    text field with placeholder `/path/to/project`. No folder picker,
    recent folders, path completion, or validation before submit. The
    project bar repeats the absolute path and a sentence that changes per
    tab.
  - **Change:** Add a server-side folder browser limited to the user's home
    directory, with recent Git repositories detected under common folders,
    path autocompletion, and live validation ("This folder is not a Git
    repository. Run `git init` here?"). Show the project name and branch in
    the header; show the full path on hover.
  - **Outcome:** Users open a project without typing a path.
  - **Done when:** Open works by click; invalid folders explain the fix.

- [x] **BX-25. Add workflow management actions.**
  - **What:** Workflow-level operations.
  - **Problem:** The UI can create and save a workflow but cannot rename,
    duplicate, delete, or disable one, and the dropdown shows only display
    names, not file names.
  - **Change:** In the workflow sidebar and header: **Rename**, **Duplicate**,
    **Delete** (with confirmation and a note that run history stays),
    **Disable** (hides Run workflow, like GitHub's disable workflow). Show
    the file name under the display name.
  - **Outcome:** Users can manage workflows without a terminal.
  - **Done when:** Each action has API, UI, and tests; deletes respect leases.
  - **Verified:** `test_workflow_management` proves rename disables old-name
    schedule, push, and dispatch triggers while preserving delivery history.
    Fresh activation at the new name launches successfully for each event.

- [x] **BX-26. Add GitHub-style re-run actions.**
  - **What:** Run-level controls.
  - **Problem:** A finished run offers no **Run again**. A failed run offers
    **Retry step** per failed node only. **Pause new steps** appears on a
    failed run where nothing can start. **Stop work** is the cancel label.
  - **Change:** Header actions by state: in progress → **Cancel run**,
    **Pause**; failed → **Re-run failed jobs**, **Re-run all jobs**;
    succeeded or cancelled → **Re-run all jobs**. "Re-run all jobs" opens
    Run workflow prefilled with the previous inputs and creates a new run.
    Per-job **Re-run job** lives in the job view. Hide controls that cannot
    act.
  - **Outcome:** Re-running works exactly like GitHub Actions.
  - **Done when:** Each control appears only in valid states, with tests.

- [x] **BX-27. Explain launch blockers before the user hits them.**
  - **What:** The clean-Git rule.
  - **Problem:** Launch rejects staged changes and unrelated edits. Users
    learn this only from an error after pressing Launch.
  - **Change:** The Run workflow panel runs the preflight on open and lists
    blocking files with a reason each ("staged", "modified", "untracked"),
    which files are allowed and why, and copyable fixes (`git stash -u`,
    `git commit`). Never run those commands for the user.
  - **Outcome:** No surprise launch failures.
  - **Done when:** The preflight result matches the server check exactly.

  The web UI guide's Launch a run and Git guide's Clean launch sections explain
  the preview; the HTTP guide documents its bounded read endpoint. Launch
  preflight and API tests compare the shared rule with launch, while the
  launch-panel browser tests cover explanations, copied fixes, and later edits.

- [x] **BX-28. Simplify the paused-run panel.**
  - **What:** **Unstarted agent steps** and pause copy.
  - **Problem:** The paused header shows a blue info box and a second
    sentence that say the same thing. **Unstarted agent steps** lists slugs
    and opens a dialog that loads for several seconds with disabled fields
    before showing "Keep current permission mode (auto_approve)".
  - **Change:** One line: "Paused. Running jobs will finish; nothing new will
    start until you resume." List upcoming jobs in the job list with an
    **Edit** icon. Prefetch choices so the dialog opens ready.
  - **Outcome:** Pause is understandable at a glance.
  - **Done when:** The dialog opens populated; duplicated copy is removed.

  The web UI guide's Monitor and control runs section covers the single pause
  message and upcoming job icons. Dispatch-pause browser tests cover shared
  probes, populated dialogs, errors, focus, reload, and cancellation; pause
  service tests verify saved settings preserve completed work and snapshots.

### P2: polish, help, and accessibility

- [x] **BX-29. In-app help and empty states.**
  - **Problem:** Empty states are single sentences. There is no help menu, no
    link from a field to its docs, and no tour.
  - **Change:** A **?** menu with "Getting started", "Coming from GitHub
    Actions" (BX-35), "Keyboard shortcuts", and docs links. Every empty state
    has a picture of what will appear and one action. Optional 4-step tour
    on first visit to the editor and the run page.
  - **Done when:** Every page and panel has a non-blank empty state.

- [x] **BX-30. Settings page.**
  - **Problem:** Login, default agents, and port live only in
    `settings.json` and CLI flags.
  - **Change:** A **Settings** page: account and login requirement (with the
    existing restart notice), default agent order, storage (BX-16), and
    notification preferences. Changes that need a restart say so.
  - **Done when:** Every documented owner setting is visible in the UI.

  The Settings section in `docs/web-ui.md` and the defaults inventory in
  `docs/projects-and-storage.md` describe every control and inheritance rule.
  `tests/test_owner_settings.py` and `frontend/e2e/settings.spec.ts` cover saves,
  conflicts, captured launches, restart notices, and browser recovery.

- [x] **BX-31. Accessibility pass.**
  - **Problem:** The editor's stage-list buttons have no accessible name (the
    accessibility tree shows 17 unnamed "button" items). Status is shown
    partly by color. The read-only graph announces delete hints.
  - **Change:** Name every control; pair color with icons and text; verify
    focus order for dialogs and drawers; run axe in browser tests.
  - **Done when:** Automated axe checks pass on every page with no serious
    issues.

- [x] **BX-32. Keep view state when switching runs.**
  - **Problem:** Switching runs keeps the previous scroll position and
    expanded panels (for example, data cleanup stayed open). During a live
    run, an expanded diagnostics panel appeared to collapse after an update
    (seen once; confirm).
  - **Change:** Reset scroll to the top on run change; persist panel state per
    panel type, not per DOM instance; ensure live updates never toggle
    disclosure state.
  - **Done when:** Browser tests switch runs and receive live events with
    panels open.

- [x] **BX-33. Expression helper.**
  - **Problem:** `if` and condition `expr` need `${{ needs.<id>.outputs.<name>
    }}` written by hand.
  - **Change:** An expression field with autocomplete for `inputs`, upstream
    `needs.*.outputs.*`, `run`, and `loop`, live validation, and a
    "Choose a value" builder (output, operator, value).
  - **Done when:** Every valid reference is suggested; invalid ones show the
    server's error inline.

- [x] **BX-34. Narrow-window layout.**
  - **Problem:** At 900 px the selected node is cut off, the minimap covers
    the canvas, and header buttons wrap ("New / workflow", "Add / stage").
  - **Change:** Collapse the workflow sidebar to icons, move job settings to
    a full-height drawer, hide the minimap, and keep header buttons on one
    line with an overflow menu.
  - **Done when:** Browser tests at 900 px and 1280 px show no clipping.

- [x] **BX-35. Write "Coming from GitHub Actions".**
  - **Problem:** The docs never mention GitHub Actions even though the syntax
    already shares `needs`, `if`, `${{ }}`, `inputs`, and `env`.
  - **Change:** A doc page with a side-by-side mapping (the vocabulary table
    above), what is the same, what differs (agents instead of runners,
    worktrees instead of checkouts, no triggers in Phase 1, argv commands
    until BX-08), and three translated examples. Link it from the README
    quick start and the help menu.
  - **Done when:** The page passes the doc link and workflow example checks.

- [x] **BX-36. Consider GitHub Actions key aliases. Needs a schema decision.**
  - **Problem:** Users will type `timeout-minutes`, `steps`, `runs-on`, and
    `continue-on-error` from habit and get "unknown key" errors.
  - **Change:** Decide between (a) friendly validation errors that suggest
    the Relay key ("`timeout-minutes` is GitHub Actions syntax; use
    `timeout: 10m`") and (b) a versioned schema that accepts the aliases.
    Ship (a) first; it needs no schema change.
  - **Done when:** Common GitHub Actions keys produce a suggestion instead of
    a bare schema error.

- [x] **BX-37. Rewrite the README quick start for beginners.**
  - **Problem:** The README's first screen is status, certification, and
    recovery details. The quick start is three commands followed by launch
    rules and exit codes.
  - **Change:** Lead with one sentence and a screenshot of the run page,
    then: install, `relay up` in your repository, pick a template, press
    **Run workflow**. Move status, certification, and safety rules lower.
  - **Done when:** A new reader can start a run from the first screen of the
    README.
  - Verified in the README Quick start and Start Relay in `docs/web-ui.md`.
    `tests/test_supervisor_lifecycle.py` covers first-start initialization
    and preservation; `frontend/e2e/get-started.spec.ts` runs the sample.

### Suggested order

1. BX-01, BX-02, BX-09: a new user can install, see agent readiness, and run
   a template.
2. BX-04, BX-05, BX-06, BX-26: the run page answers "what happened, what do
   you need from me, run it again".
3. BX-03, BX-14, BX-17, BX-18: the app looks and reads like GitHub Actions.
4. BX-07, BX-10, BX-21, BX-22: the editor delivers the "edit any YAML option
   in the browser" promise.
5. BX-08 and BX-36 after an explicit schema and security decision.
6. Remaining P1 and P2 items.

## Skill-based UI audit

This audit ran on 2026-10-09 against `main` at `4b25f4e`. It used five
review skills, one at a time, after mapping every flow in the app. Each
skill's findings are kept in their own subsection, in that skill's
required output format.

How it was run:

- **Owner instance** (`127.0.0.1:17945`, projects `suspendit` and `relay`):
  read-only. Pages were opened, scrolled, and tabbed through; nothing was
  launched, answered, saved, or cleaned. Opening the editor briefly took the
  normal 60-second editor lease; no files or records changed.
- **Isolated instances**: `tests/e2e_server.py` on port 4190 (login off)
  and 4191 (login on), with scratch storage and fake agents. Mutating
  journeys and worst-case data used only these, through the public HTTP
  API, the same boundary the UI uses.
- **Tools**: Playwright with Chromium for journeys and screenshots, the
  Chrome DevTools Protocol for metrics, and axe-core 4 for accessibility.
  The Chrome DevTools MCP named by `browser-testing-with-devtools` is not
  configured here; Playwright's CDP session supplied the same data.
- **Widths**: 320, 375, 768, 1024, and 1440 pixels, plus 200% root text
  size and an emulated dark color scheme.

### Flow map

Every user-facing flow, its entry point, and the passes that covered it.
DT = devtools, QA = browser-qa, BR = break-ui, DE = emil-design-eng,
FE = frontend-ui-engineering.

| # | Flow | Entry point | What the user does | Passes |
| --- | --- | --- | --- | --- |
| F01 | Install and start | `relay init`, `relay up [--no-login]`, `relay doctor` | Prepare a repository, start the server, check agents | FE (source) |
| F02 | First login and sign-in | `/` with login on | Create the owner, sign in, sign out, recover from a wrong password | QA |
| F03 | Welcome slides and guided tour | First visit; Help menu; Settings › Welcome and guided tour | Read 4 slides, then a spotlight tour; replay or reset | QA, DE |
| F04 | Get started checklist | Welcome banner **Get started**; Help › Get started | Check agents, pick a template, run it | QA, DT |
| F05 | Empty installation | `/` with no projects | **Open your first project** | FE (source) |
| F06 | Home dashboard | Logo; `?view=home` | Waiting requests, active and paused runs, recent results, project cards, search | DT, QA, BR, DE |
| F07 | Switch or open a project | Project picker; **Open another project** (path field and folder browser) | Choose a registered repository or add one | QA, BR |
| F08 | Workflow selection | Workflows tab; workflow picker | Pick a workflow; empty-project state | QA, BR, FE |
| F09 | Create a workflow | **Create workflow** / **New workflow** | Choose one of seven starters or a blank workflow | QA |
| F10 | Visual editing | Canvas and job form | Add and remove jobs and steps; set needs, conditions, timeouts, matrix, outputs, env, concurrency | QA, BR, FE |
| F11 | YAML editing | Workflow YAML panel | Type YAML, see validation, save, recover drafts, handle lease conflicts | DT, QA, BR |
| F12 | Agent step settings | Agent step in the job form | Agent, exact model, effort, permissions, instructions | FE (source) |
| F13 | Repair rules | **Repairs** on a stage | Fixer and verifier, rounds, accepted verdict | FE (source) |
| F14 | Variables, secrets, environments, library | **Variables, secrets, environments and library** | Bindings, environments, export and import, triggers | FE (source) |
| F15 | Run workflow | **Run workflow** (editor, run header, checklist) | Inputs, project-file preflight, advanced options, launch | QA, DE |
| F16 | Run history | Runs tab; **Run history** | Workflow sidebar, search, status and branch filters, load older | DT, QA, BR |
| F17 | Run summary | A run | Header, graph, annotations, run settings, artifacts, workflow file | DT, QA, BR, DE |
| F18 | Job log | A job in the sidebar or graph | Sections, search, timestamps, full screen, raw, copy, download, follow, attempts | DT, QA, BR |
| F19 | Respond to a request | Home **Open request**; waiting banner; deep link | Answer a human wait, permission, or elicitation | QA |
| F20 | Run controls | Run header | Cancel, pause and resume new steps, change unstarted steps | QA |
| F21 | Recovery | **Re-run jobs**; **Re-run job**; Run settings | Re-run all or failed jobs, retry with settings, automatic recovery | QA |
| F22 | Review material | Approval card; Summary | Reports and committed diff | QA |
| F23 | Global defaults | Settings › Global defaults | Agents, models, commands, variables, timeouts, retries, cleanup, repairs | QA, DT |
| F24 | Project defaults | Settings › Project defaults | Per-project overrides | QA |
| F25 | Server and account | Settings › Server and account | Login, address, port | QA |
| F26 | Notifications | Settings › Notifications; Help | Desktop notifications | QA |
| F27 | Storage and cleanup | Settings › Storage | Sizes, confirmed cleanup, temporary resources | QA, BR |
| F28 | Help and tooltips | Help menu; `?` buttons | Get started, slides, tour, notifications, field help | QA, DE |
| F29 | Deep links and history | URL parameters; Back and Forward | Reopen a run, job, or request; restore selection | DT, QA |
| F30 | Live updates | Any run page | SSE stream, polling, refresh, attention count in title | DT |
| F31 | Load failures | Any view | **Reload Relay** boundary; retry banners | FE (source) |
| F32 | CLI administration | `relay project`, `relay data clean` | Relink projects, delete retained data | FE (source) |

### browser-testing-with-devtools

Console, network, performance, computed styles, and the accessibility tree.
Evidence comes from your instance unless it says "isolated".

- [x] **DT-01. Editor leases lock people out of their own workflow.**
  - **Evidence:** Closing a tab never releases its 60-second lease. Opening
    the same workflow in a new tab, or after a browser restart, shows "Another
    browser holds the workflow editor lease", disables Save and **Restore
    saved source**, and logs a 409 console error on every load. This was
    reproduced on both instances. A `POST /api/workflows` that fails
    validation also leaves a lease behind.
  - **Fix:** Release the lease on `pagehide` with `navigator.sendBeacon`.
    Replace the error with "This workflow is open in another tab. **Edit
    here instead**", where an explicit takeover invalidates the other holder.
    Never acquire a lease for a create that fails validation. Say "another
    tab or browser", and stop logging an expected 409 as a console error.
  - **Done when:** Closing a tab and reopening the workflow allows editing
    immediately, takeover is tested across two tabs, and contested loads
    leave a clean console.

- [x] **DT-02. The same data is fetched twice on load.**
  Verified by `data-layer.spec.ts` "each page loads each initial resource once"
  on Home, Runs, finished and running runs, and a job page. The test counts
  every initial GET and requires one attention read per load.
  `waiting-requests.spec.ts` also forces a late pending-request response and
  proves live invalidation keeps the answered request cleared.
  - **Evidence:** Home requests `GET /api/dashboard?limit=10` twice. A run
    page requests `/artifacts?since=0` twice. The job page's
    `/api/runs/{id}/job` request is aborted and sent again at 375 px.
  - **Fix:** Route reads through one cache that deduplicates in-flight
    requests (see FE-02), and fetch from an effect keyed on stable IDs.
  - **Done when:** Each resource is requested once per page load.

- [x] **DT-03. Finished runs still open a live stream and replay history.**
  - **Evidence:** Opening the failed run #22 opened
    `/api/runs/{id}/stream?since=50152` and received 280 KB of events for a
    run that ended days earlier. The job page did the same.
  - **Fix:** For terminal runs, load the needed pages and skip the
    stream. Open it only when the run is active or a re-run starts.
  - **Done when:** A terminal run page opens no EventSource and transfers
    under 100 KB of event data.

- [x] **DT-04. Background polling never backs off.**
  - **Evidence:** In 20 idle seconds every page called `/api/attention`
    4 times, and Home also called `/api/dashboard` 4 times.
  - **Fix:** Pause polling while `document.hidden`, back off to 30 seconds
    after a minute of no changes, and resume on focus. Prefer one shared
    attention stream over per-page polling.
  - **Done when:** A hidden tab makes no polling requests, and an idle
    visible tab polls at the backed-off rate.

- [x] **DT-05. The JavaScript is large and uncompressed, and Run workflow
  waits for a chunk.**
  - **Evidence:** The entry bundle is 626 KB and is served without
    `Content-Encoding`. `LaunchPanel` is a 292 KB chunk that loads on the
    run list and again on the first **Run workflow** click; the dialog took
    about 800 ms to appear (isolated).
  - **Fix:** Serve precompressed `.br`/`.gz` assets from the static view.
    Split CodeMirror and the carousel out of `LaunchPanel`. Preload the
    launch chunk on hover and focus of **Run workflow**.
  - **Done when:** Entry JavaScript transfers under 200 KB, and the launch
    dialog opens in under 150 ms after the chunk is cached.

- [x] **DT-06. Old frontend builds pile up and source maps ship.**
  - **Evidence:** `relay/static/assets` holds 288 MB in 1,130 files,
    including 557 `.map` files and 27 entry bundles. `scripts/publish.mjs`
    keeps every earlier chunk forever, and `vite.config.ts` sets
    `sourcemap: true` with no exclusion from the wheel.
  - **Fix:** Keep only chunks referenced by the last few entry pages. Use
    `sourcemap: "hidden"` for development builds and exclude `.map` from the
    wheel. Make `scripts/check_distribution_contents.py` reject maps.
  - **Done when:** Repeated builds keep the asset folder bounded, and
    `make check-dist` fails on a `.map` file.

- [x] **DT-07. Landmarks and headings are inconsistent.**
  - **Evidence:** Only Home has a `main` landmark. Run pages have two
    `header` elements, and the run header is `<header role="region"
    aria-label="Workflow run history">`, which is the wrong label and a
    disallowed role. Workflows has no `h1`; Settings starts with `h6`; Home
    jumps from `h1` to `h4`.
  - **Fix:** One `main` in the app shell. One `h1` per view (the workflow,
    run, or settings section name) and sequential levels below it. The run
    header becomes a plain `header` inside `main`, labelled by its `h1`.
  - **Done when:** axe reports no `landmark-*`, `page-has-heading-one`, or
    `heading-order` issues on any page.

- [x] **DT-08. Navigation and lists are buttons, not links.**
  - **Evidence:** The header uses MUI Tabs, so Tab reaches only the
    selected tab; the others need arrow keys. Job list rows are
    `div role="button"`. Home's **Open request** is a `<button>`. None of
    them can be opened in a new tab, or have their link copied.
  - **Fix:** Render header navigation as links with `aria-current="page"`,
    job rows as links to `&job=`, and **Open request** as a link to its
    interaction URL.
  - **Done when:** Every navigation target is a link that works with
    middle-click, and Tab reaches every header destination.

- [x] **DT-09. Keyboard users wade through the header on every page.**
  - **Evidence:** Eight tab stops come before page content. On the paused
    run, about 40 stops (every job) come before the summary.
  - **Fix:** Add a "Skip to content" link. Put the job list after the
    summary in DOM order on narrow screens, or add a "Skip job list" link.
  - **Done when:** Content is reachable within 2 tab stops from the top.

- [x] **DT-10. Focus styling is wrong in three places.**
  - **Evidence:** Programmatic focus on the job title draws a full
    input-like rectangle around the heading. React Flow nodes and edges are
    focusable in the read-only run graph with no visible focus style, and
    edges take focus while off-screen.
  - **Fix:** Use `tabIndex={-1}` headings with no outline unless
    `:focus-visible`. Set `edgesFocusable={false}` on read-only graphs, and
    add a `:focus-visible` style to graph nodes.
  - **Done when:** A tab walk shows a visible indicator on every stop and
    no indicator on programmatic heading focus.

- [x] **DT-11. Small and low-contrast text.**
  Verified by `visual-regression.spec.ts` on all seven normal and worst-case
  screens: axe contrast and target-size checks pass, and visible history text
  is at least 12 px with weights 400, 500, or 600.
  - **Evidence:** "All jobs" is `#67738b` on `#f4f6fb`, 4.41:1. The React
    Flow attribution is 2.79:1 and a 52×12 px target. The paused run page
    has 69 text nodes at 11 px; field labels are 10.5 px.
  - **Fix:** Darken the secondary text token to at least 4.5:1 on every
    surface. Use 12 px as the minimum text size. Move or restyle the
    attribution after checking React Flow's attribution policy.
  - **Done when:** axe `color-contrast` and `target-size` pass everywhere.

- [x] **DT-12. Fix the remaining axe violations.**
  Verified by `visual-regression.spec.ts`: every normal and worst-case screen
  passes serious/critical axe rules, including WCAG 2.1 A and 2.2 AA.
  `accessibility.spec.ts` also checks every visible Home path name and audits
  the disclosure both closed and open, including its Copy path button.
  - **Evidence:** One critical rule (`aria-allowed-attr` on
    `.project-context` during the tour). Serious: the CodeMirror editor has
    no accessible name (`aria-input-field-name`); MUI `<ul>` elements contain
    non-`li` children in 8 views (`list`); job rows and disclosures have
    accessible names that exclude their visible text in 8 views
    (`label-content-name-mismatch`). Moderate: two `banner` landmarks during
    the tour, and 148 nodes outside landmarks.
  - **Fix:** Label the editor "Workflow YAML", render list children as
    `li`, build accessible names from the visible text, and keep tour
    overlays outside landmark roles.
  - **Done when:** axe reports no critical or serious violations on any
    flow in the map.

### browser-qa

#### QA report: isolated instances and owner read-only, 2026-10-09

##### Smoke test

- **Console:** 2 real errors. React error #185 ("Maximum update depth
  exceeded", from an `update listener`) appeared once while replacing the
  whole YAML document; a focused re-run did not reproduce it. Expected 409
  and 401 responses are also logged as errors (DT-01, QA-09).
- **Network:** no 5xx responses. Expected 401 (signed out), 400 (invalid
  settings), and 409 (lease) only.
- **Core Web Vitals:** LCP passes, 84–1,064 ms. CLS fails on run pages:
  0.45–0.55 at 375 px and 0.11–0.18 at 1440 px. Home is 0.21 at 375 px.
  INP was not measured.

##### Interactions

- [✓] Header navigation, logo, and Help menu: 4 menu items, no dead links.
- [✓] Get started checklist: agent cards, install links, template choice.
- [✓] Create from template: six starters with previews and inputs.
- [✗] Run a second workflow after creating one: blocked (QA-01).
- [✗] Reopen a workflow after an invalid edit: stranded (QA-02).
- [✗] Invalid YAML feedback: no reason, blank canvas (QA-03, QA-04).
- [✗] Required launch input: browser-native bubble only (QA-07).
- [✓] Approval: answered and continued; lowercase `approved` passes, which
  matches GitHub's case-insensitive `==`.
- [✗] Approval card wording and controls (QA-06).
- [✓] Cancel run with confirmation; **Re-run all jobs** offered afterwards.
- [✗] Settings validation and section guard (QA-05).
- [✓] History search with a no-match state: "No runs match these filters."
- [✓] Job log options: timestamps, full screen, download, raw, copy.
- [✓] Login, wrong password ("The username or password is not valid."),
  sign out, sign in. First-owner onboarding was not reachable because the
  fixture creates its owner at startup.

##### Visual

- INCONCLUSIVE: no committed screenshot baselines exist (QA-12).
- [✗] Run pages overflow at 320 px, and the phone header clips its tabs
  (BR-02, BR-03).
- [✓] Dark mode: the app supports System, Light, and Dark themes (PR #17).

##### Accessibility

- 1 critical rule, 5 serious rules, and 7 moderate or minor rules across
  15 views (DT-07 to DT-12). Keyboard navigation works end to end, but the
  costs are listed in DT-08 and DT-09. No screen-reader pass was run.

##### Verdict: DO NOT SHIP to beginners

QA-01 and QA-02 strand a new user without an explanation they can act
on. Everything else is SHIP WITH FIXES.

- [x] **QA-01. Creating a workflow blocks every other workflow from
  running. Blocker; contract change.**
  - **Evidence (isolated):** After creating "New workflow" from a template,
    `GET /api/workflows/{key}/preflight` returned `clean: false` for every
    other workflow ("1 file blocks this run.
    .relay/workflows/new-workflow.yaml untracked"). Only the new workflow
    could launch. A beginner who tries two starters can't run the first one.
  - **Fix:** Pick one, with owner approval because it changes
    `relay/vcs/cleanliness.py`:
    1. Exempt untracked, validated files under `.relay/workflows/` and
       `.relay/prompts/` that the launched workflow does not reference.
       Runs start from the committed head, so those files cannot affect
       the run.
    2. Keep the rule, and add **Commit workflow files** to the preflight
       panel: a preview, an explicit confirmation, and one commit containing
       only those paths.
  - **Done when:** Creating two starters back to back lets both run, with
    a browser test.
  - **Verified:** `test_workflow_publication` proves the selected untracked
    workflow and captured prompts can be reviewed and committed, preserving
    unrelated owner files. `editor-recovery.spec.ts` proves the commit dialog
    works when that workflow is the only untracked source.

- [x] **QA-02. One bad edit can strand the editor. Blocker.**
  - **Evidence (isolated):** An invalid YAML edit autosaves as a recovery
    draft. A new tab restores that draft automatically. While another
    holder's lease is live, **Restore saved source** and **Run workflow**
    are disabled, even though the saved file is valid.
  - **Fix:** **Run workflow** always runs the saved file and says so when a
    draft exists ("Your unsaved draft is not included"). Show the draft
    beside the saved source with a diff, and let the user discard the draft
    without holding the lease.
  - **Done when:** An invalid draft never blocks running the saved
    workflow.

- [x] **QA-03. "Invalid YAML document" gives no reason.**
  - **Evidence:** `run: echo "Task: ${{ inputs.task }}"` (an unquoted colon,
    a classic YAML trap) returned only "Invalid YAML document." with a line
    and column. The banner reads "Line 6: Invalid YAML document." The canvas
    goes blank, with no message inside it.
  - **Fix:** Show the parser's reason in plain words, with a hint for common
    traps ("Quote a value that contains a colon followed by a space").
    Underline the position in CodeMirror. Keep the last valid graph,
    greyed out, with "Showing the last valid version".
  - **Done when:** The ten most common YAML mistakes each show a reason and
    a fix hint, with unit tests.

- [x] **QA-04. Validation reports one error at a time.**
  - **Evidence:** A workflow using `runs-on: ubuntu-latest`,
    `timeout-minutes`, and `uses: actions/checkout@v4` returned only the
    `runs-on` error ("Use self-hosted for Relay's local runner.").
  - **Fix:** Return every independent diagnostic, mark each in the editor,
    and keep the helpful "use self-hosted"-style suggestions for each
    GitHub-only feature.
  - **Done when:** That workflow lists all of its problems at once.

- [x] **QA-05. Settings errors appear late, in the wrong place, and leak
  internals.**
  - **Evidence (isolated):** **Save global settings** accepted a job
    timeout of `soon`. The error appeared at the top of the page as "Invalid
    workflow defaults: timeout: Value error, Use a duration such as 30s, 15m,
    or 2h", including Pydantic's "Value error," prefix. It stayed visible
    after switching to **Storage**, and the switch with unsaved changes was
    not blocked, although `docs/web-ui.md` says it is.
  - **Fix:** Validate each field as it is typed, with helper-text errors.
    Strip validator prefixes when building `RelayError` messages. Scope
    errors to their section. Guard section changes with "Discard or keep
    editing".
  - **Done when:** An invalid value can't be saved, the error sits under the
    field, and other sections stay clean.

- [x] **QA-06. Approvals ask the user to type a magic word.**
  `waiting-requests.spec.ts` verifies completed attempts and exact answer
  outputs after a missing stream tail or a late pending read.
  `test_terminal_events_committed_after_an_empty_read_are_replayed` proves
  the server delivers the final answer and completion events before closing.
  - **Evidence (isolated):**
    - **Free-text answer:** the request says "Type Approved to continue"
      above a free-text box. There are no Approve or Reject buttons.
    - **Unexplained deadline:** the card shows "Respond before 5:20:39 PM",
      the 6-hour default job timeout, although the workflow declared none.
    - **Missing button:** the summary says "Choose Respond above", but no
      Respond button exists.
    - **Empty review picker:** a "Committed code changes" picker appears
      even when nothing changed.
    - **Steps shown as jobs:** the step appears as a job named `approval`,
      next to `step_2`.
  - **Fix:** Add an optional `options:` input to `relay/human-wait@v1`, and
    render the options as buttons, with free text available alongside. Say
    "Expires in 6 hours (default job timeout)". Fix the copy, hide empty
    review material, and show steps inside their job (BR-04).
  - **Done when:** An approval is one click, and its expiry is explained.

- [x] **QA-07. Required launch inputs rely on the browser bubble.**
  - **Evidence:** With **Task** empty, **Run workflow** stayed enabled and
    the only feedback was Chrome's native "Please fill out this field."
  - **Fix:** Show inline MUI errors on submit, and focus the first invalid
    field.
  - **Done when:** Every input type shows an inline error, with a test.

- [x] **QA-08. Overlays stack on a first visit, and the welcome banner
  never leaves.**
  - **Evidence:** Escape on the welcome slides starts the guided tour
    immediately. Your instance, with 25 runs, still shows "New to Relay?
    Check agents and choose your first workflow." on every page.
  - **Fix:** End the slides with an explicit **Take the tour** button.
    Hide the banner automatically after the first successful run.
  - **Done when:** A first visit shows one overlay at a time, and
    experienced projects never see the banner.

- [x] **QA-09. Home contradicts itself in small ways.**
  - **Evidence:** "Unfinished runs 1" appears beside "No jobs are running or
    paused". Every recent result shows "Detached HEAD" as its branch.
    "Latest results" repeats "Recent results". A signed-out page logs a 401
    console error.
  - **Fix:** Count waiting runs in the unfinished list, show the recorded
    source branch or "no branch", drop the duplicate label, and treat 401 as
    a normal signed-out state.
  - **Done when:** The tiles always agree with the lists below them.

- [x] **QA-10. GitHub Actions words are still missing in run states.**
  - **Evidence:** Cancelled runs say "Stopped". Rows read "Started by local"
    in no-login mode.
  - **Fix:** Use "Cancelled", and show "Started by you" when login is off.
  - **Done when:** The status vocabulary matches the BX vocabulary map.

- [x] **QA-11. Layout shift fails Core Web Vitals on run pages.**
  Verified by `visual-regression.spec.ts` delayed-response CLS checks across
  seven worst-case screens at 320, 375, and 1440 px, each below 0.1, with the
  setup banner undismissed so startup shifts cannot escape the gate. The tests
  retain `layout-shift` source rectangles and clean up delayed routes. A held
  project-inventory response also proves header controls keep their rectangles
  before and after loading, including wider fallback font metrics.
  - **Evidence:** The largest shift, 0.256 at 375 px, is the job sidebar
    rendering "Jobs will appear" and then the list (a 231 px jump). The
    next, 0.138, is the header reflowing when projects load.
  - **Fix:** Render a skeleton with the final dimensions, and give the
    header its final shape on the first paint.
  - **Done when:** CLS is below 0.1 on every page at 375 and 1440 px.

- [x] **QA-12. Add visual baselines.**
  Verified by all 21 normal-screen `visual-regression.spec.ts` captures in
  Linux CI run 38072518542, with its reviewed baseline artifact committed under
  `baselines/linux`. Separate reviewed macOS baselines pass the same spec.
  - **Evidence:** No screenshot baselines exist, so regressions in this
    audit could only be judged by eye.
  - **Fix:** Add `toHaveScreenshot` baselines for Home, Workflows, Runs,
    run summary, job log, approval, and Settings at 375, 768, and 1440 px,
    using the isolated fixture.
  - **Done when:** `make test-frontend` fails on visual drift.

### break-ui

Worst-case data went in through the public API on the isolated instance:
four projects (a 72-character hyphenated name, `王秀英-客户端`,
`نور-الهدى`, and `j`), a workflow name with `<script>`, `**`, and
`&amp;`, a 2,000-character `run-name` with an email, CJK, Arabic, and a
ZWJ emoji, a 90-character job ID, a 41-job fan-out, a 20,000-line log
ending in exit 3, and 154 runs. The skill's dev-only **Demo / Worst case**
toggle was not wired into the app, because this audit changes no product
code; BR-14 adds it.

#### Part 1: What broke

| # | Severity | Field | Worst-case value | What happens | Fix |
| --- | --- | --- | --- | --- | --- |
| 1 | Broken | `run.title` (`run-name`) | 2,000-character ticket text | The run `h1` wraps to 32 lines at 1440 px and 81 at 320 px; the back link repeats the full text | Clamp the `h1` to 2 lines, with **Show full title**; the back link shows the workflow name |
| 2 | Broken | Run header at 320 px | Long title plus `#5` | Page scrolls sideways; `#5` sits at x=432 on a 320 px screen | `min-width: 0` on the title, `flex-shrink: 0` on the number, wrap the actions |
| 3 | Broken | App header at 320–375 px | Normal labels | Tabs clip to "Setti…", Help overlaps them | Collapse the navigation into a menu below 480 px |
| 4 | Broken | Job list and counts | 41 jobs, one step each | "82 jobs"; `step_1` listed 41 times as a job; the job page says "Output will appear here when this job starts" and "0 messages" for a failed job | Show jobs only; steps become sections in the job log with their own output and exit code |
| 5 | Broken | Step page | Exit 3 | Titled "Job failed with exit code 3" with **Re-run job** | Steps appear inside their job (row 4) |
| 6 | Ugly | Run graph | 41 parallel jobs | No "N parallel jobs" group (each job's own step makes its edges unique); 41 cards run off the right edge; "Child complete" labels overlap; page height 18,409 px at 1440 and 44,735 px at 320 | Group on job-level edges, ignoring child scopes; hide junction labels |
| 7 | Ugly | Artifacts | 41 echo jobs | 164 artifacts, mostly `0 B` `commits` and `worktree_diff` | Hide empty internal evidence (BX-15) |
| 8 | Ugly | Truncated text | Long paths and names | Project paths, history workflow titles, sidebar workflow names ("Konstantin Oberhaus…"), and the Storage project name truncate with no title or tooltip | Add a title or tooltip; middle-truncate paths |
| 9 | Ugly | Editor workflow picker | Long workflow name | The picker grows to the full name and pushes the buttons; canvas nodes wrap to 5 lines beside 1-line nodes | `max-width` with ellipsis; fixed node height with a 2-line clamp |
| 10 | Ugly | Queued runs | 150 queued runs | Same clock icon as running runs; durations count up while queued | A **Queued** status; duration starts at `started_at` |
| 11 | Ugly | Durations | 67 hours | "67h 11m 36s"; paused time counts as run time | Roll over to days ("2d 19h"); show paused time separately |
| 12 | Fragile | `name`, `run-name`, job `name`, input `description` | — | Unbounded in the schema and in `Run.title` | Add limits (e.g. 256 characters for names, 1,000 for run titles) and match them in the UI |
| 13 | Fragile | Counts | `{n} jobs`, `runs`, `working copies` | Hardcoded plurals (`RunWorkspace.tsx:894`, `StorageSettings.tsx:45,74`) | `Intl.PluralRules` |
| 14 | Fragile | Dark mode | `prefers-color-scheme: dark` | Supported via System, Light, and Dark mode tokens; no flash on boot | Implemented in `feat/dark-mode` (PR #17) |

Fix locations: `frontend/src/components/RunWorkspace.tsx` (rows 1, 2, 4, 5,
10, 11), `frontend/src/run-graph.ts:7-37` (row 6), `frontend/src/App.tsx`
and `frontend/src/styles.css` (row 3), `ActionsWorkflowWorkspace.tsx`
(row 9), `relay/workflows/actions/language.py` and `relay/web/models.py`
(row 12).

- [x] **BR-01. Clamp the run title** (rows 1 and 12).
  `title-clamp.spec.ts` proves the title stays within two lines and its run
  number stays visible at 320, 375, and 1440 px; the dialog shows all text.
- [x] **BR-02. Make the run header fit 320 px** (row 2).
- [x] **BR-03. Give the app header a phone layout** (row 3).
- [x] **BR-04. Show steps inside jobs, as GitHub does** (rows 4 and 5).
  The job page lists its steps as collapsible sections with their own
  output, exit code, and duration; the sidebar and counts show jobs only.
- [x] **BR-05. Group wide fan-outs and keep the graph on screen** (row 6).
  Replace the O(nodes × edges) edge filtering with source and target maps.
- [x] **BR-06. Hide empty internal artifacts** (row 7).
- [x] **BR-07. Give truncated text a way to read it** (row 8).
- [x] **BR-08. Bound the editor picker and node sizes** (row 9).
- [x] **BR-09. Add a Queued state and honest durations** (rows 10, 11).
- [x] **BR-10. Use plural rules** (row 13).
  `editor-recovery.spec.ts` proves "Commit 1 reviewed file" and completes the
  commit; `singular-labels.spec.ts` proves one repair round and one artifact byte.
  These counts and parallel-job counts use the shared `countLabel` helper.
- [x] **BR-11. Add a worst-case fixture and toggle.** Add the data above
  to `tests/e2e_server.py` behind a test-only `/__test__/worst-case`
  route, with a Playwright spec that loads each screen at 320 and 1440 px
  and fails on horizontal scroll or clipped primary actions. Never ship it
  in the wheel.

#### Part 2: Decisions for you

- **Run titles:** clamp to 2 lines with an expander (recommended) rather
  than truncating, because the title is how people find a run.
- **Long job names in lists:** wrap to 2 lines and then truncate with a
  tooltip, because the name identifies the job.
- **Paths:** truncate in the middle, because repositories differ at the end.
- **History length:** keep the 50-row pages with **Load older runs**; it
  handled 154 runs smoothly, so virtualization isn't needed.
- **Dark mode:** defer until colors are tokens (FE-03); emulated dark mode
  shows the light theme, which is consistent, not broken.

#### Part 3: What held up

- `<script>alert(1)</script>`, `**release**`, and `&amp;` render as literal
  text everywhere: one escaping layer, no injection.
- The 20,000-line log renders 42 DOM rows (virtualized) and stays
  searchable.
- History pagination, the "No runs match these filters." empty state, and
  the empty-project Runs page all behave.
- CJK and Arabic project names render correctly; 200% root text size causes
  no horizontal scroll on Home or Runs.
- Home stat tiles and the run list handle 154 runs without layout breaks.

### emil-design-eng

Interaction feel and visual craft, measured in the browser and read from
`frontend/src/styles.css` and `frontend/src/theme.ts`.

| Before | After | Why |
| --- | --- | --- |
| No press feedback: buttons show no transform and no ripple while pressed | `transform: scale(0.97)` on `:active` with `transition: transform 160ms ease-out` | A button must confirm that it heard the press |
| Button hover transitions `background-color, box-shadow, border-color` over 250 ms | `background-color 150ms ease` only | Hover feedback should be immediate and touch one property |
| `.MuiTabs-indicator` uses `transition: all` | `transition: transform 200ms ease-out, width 200ms ease-out` | Name the exact properties; avoid `all` |
| **Run workflow** dialog appears about 800 ms after the click (292 KB chunk loads first) | Preload on hover and focus; open the dialog at once with a skeleton | Perceived speed is set by the first frame after the click |
| Live durations and counts use proportional figures and tick every second | `font-variant-numeric: tabular-nums` on durations, counts, and times | Ticking numbers must not change width |
| Programmatic focus on the job title draws an input-like rectangle | No outline on `tabIndex={-1}` headings unless `:focus-visible` | A heading should not look like a field |
| Nine font weights (400, 500, 600, 650, 680, 700, 720, 750, 760) and ten sizes (10, 10.5, 11, 12, 13, 13.33, 14, 16, 23, 24 px) | Three weights (400, 550, 700) and a six-step scale (12, 13, 14, 16, 20, 24 px) | Fewer steps read as a system, not drift |
| Hover styles (`.run-graph-node:hover`, `.diff-file-button:hover`) apply on touch | Wrap them in `@media (hover: hover) and (pointer: fine)` | Taps trigger false hover states |
| Help tooltips wait about 185 ms every time, even after one just closed | `enterNextDelay={0}` and no transition for subsequent tips | Moving across help icons should feel instant |
| Escape on the welcome slides launches the guided tour | End the slides with an explicit **Take the tour** | Don't chain overlays the user didn't ask for |
| The job sidebar renders "Jobs will appear", then jumps 231 px | A skeleton with the final row heights | Layout stability is part of feel |
| No `prefers-reduced-motion` handling | `@media (prefers-reduced-motion: reduce)` removes transform animation and keeps opacity | Motion sensitivity |
| Graph edges carry "Child steps" and "Child complete" labels that overlap | Hide junction labels; draw plain connectors | Labels on every edge are noise |
| Header takes two rows and 107 px below 1,050 px | One row with an overflow menu | Content gets the space |
| Accordions rotate a right chevron 90°, while the log section uses a down chevron | One chevron convention everywhere | The same control should look the same |

- [x] **DE-01. Add press feedback and tighten hover transitions** (rows 1–3).
- [x] **DE-02. Make Run workflow open instantly** (row 4; see DT-05).
- [x] **DE-03. Use tabular figures for every live number** (row 5).
- [x] **DE-04. Reduce the type scale and weights** (row 7) through
  Verified by the history typography assertions in `visual-regression.spec.ts`:
  visible text uses at least 12 px and weights 400, 500, or 600. Floating filter
  labels and the Relay home link now follow that scale.
  `theme.ts` tokens.
- [x] **DE-05. Gate hover on pointer type and make tooltips instant after
  the first** (rows 8 and 9).
- [x] **DE-06. Stop layout jumps and chained overlays, and respect reduced
  motion** (rows 6, 10, 11, 12).
- [x] **DE-07. Calm the graph and the header** (rows 13–15).

### frontend-ui-engineering

Production engineering benchmarks applied to `frontend/src`.

- [x] **FE-01. Split the oversized components and add lint gates.**
  - **Evidence:** `RunWorkspace.tsx` is 1,003 lines and 53 KB, `App.tsx`
    is 23 KB, and `ActionsWorkflowWorkspace.tsx` is 23 KB with single lines
    of 1,374 characters. The skill flags components over 200 lines. The
    frontend has no ESLint or Prettier configuration, so nothing checks
    hooks or JSX accessibility.
  - **Fix:** Split `RunWorkspace` by responsibility: header, job sidebar,
    summary, graph, annotations, and requests. Add Prettier and ESLint with
    `react-hooks` and `jsx-a11y` to `make check`, as new dev dependencies
    with owner approval.
  - **Done when:** No component exceeds about 300 lines, and lint runs in
    the repository gates.

- [x] **FE-02. Add a small data layer.**
  - **Evidence:** Each view hand-rolls `fetch`, polling, and abort logic,
    with 12 `useEffect` calls in `RunWorkspace` and 9 in `App`. That causes
    DT-02 and DT-04.
  - **Fix:** Add one shared hook for keyed requests that deduplicates,
    aborts, pauses when hidden, and backs off. Use an in-repo helper, or
    TanStack Query with approval.
  - **Done when:** Every read goes through it, and DT-02 and DT-04 pass.

- [x] **FE-03. Turn colors and spacing into tokens.**
  - **Evidence:** `styles.css` has about 104 hex values and the components
    another 23; `theme.ts` defines only primary, secondary, and two
    backgrounds. `#67738b` causes the contrast failure in DT-11.
  - **Fix:** Define semantic palette tokens (text primary and secondary,
    border, surface, status colors) in the MUI theme, and expose them as
    CSS variables. Replace raw hex values. Every text token must meet 4.5:1.
  - **Done when:** No raw hex remains outside `theme.ts`.

- [x] **FE-04. Use one set of breakpoints and test them.**
  - **Evidence:** The CSS uses six unrelated breakpoints (600, 760, 800,
    900, 980, 1,050 px). The header clips at 320–375 px, run pages overflow
    at 320 px, the graph clips at 375 px, and at 1,024 px the editor stacks
    with its only node at the bottom of a tall empty canvas.
  - **Fix:** Use the MUI theme breakpoints everywhere, fit the canvas to its
    nodes on load, and add 320, 768, 1,024, and 1,440 px to the Playwright
    visual specs (QA-12).
  - **Done when:** Every flow in the map works at all four widths.

- [x] **FE-05. Give every view all five states.**
  - **Evidence:**
    - **Spinners:** loading uses spinners (`CircularProgress` in five
      components), not skeletons.
    - **Wrong empty state:** a finished job says "Output will appear here
      when this job starts".
    - **Copy without a control:** the approval summary refers to a Respond
      button that doesn't exist.
    - **Invalid YAML:** it empties the canvas.
  - **Fix:** Write a state matrix (loading, empty, error, success, no
    permission) for Home, Workflows, Runs, run summary, job log, and
    Settings, and test each state.
  - **Done when:** Each state has a test and copy that matches the
    controls on screen.

- [x] **FE-06. Replace raw JSON fields in the job form.**
  - **Evidence:** "Matrix and strategy", "Job outputs", "Environment",
    "Concurrency", and "Step environment variables" are `{}` JSON text
    areas with "JSON values; YAML comments and unrelated fields are
    preserved". "Needs" is a comma-separated text field.
  - **Fix:** Key-value tables for env and outputs, a multi-select for
    needs, a matrix builder, and a concurrency group field with a
    cancel-in-progress switch. Keep JSON as an advanced option. This
    completes BX-07.
  - **Done when:** A beginner can set each of these without typing JSON.

- [x] **FE-07. Make workflow and run navigation consistent.**
  - **Evidence:** Runs uses a GitHub-style workflow sidebar; Workflows uses
    a dropdown and has no `h1`.
  - **Fix:** Share one workflow sidebar between both views, as the GitHub
    Actions tab does, and title the editor with the workflow name as `h1`.
  - **Done when:** Switching between Workflows and Runs keeps the same
    sidebar and selection.

- [x] **FE-08. Gate accessibility in CI.**
  Verified by `visual-regression.spec.ts` and the automatic `a11y-test.ts`
  fixture. Explicit audits cover every screen in loops, including stress data,
  while `activity-feed.spec.ts` proves paging preserves a visible focus
  destination below the header without obscuring graph targets. Home path
  names receive explicit visible-name assertions and closed/open axe checks
  in `accessibility.spec.ts`.
  - **Evidence:** Today's sweep found 1 critical and 5 serious axe rules
    that the existing browser tests did not catch.
  - **Fix:** Add `@axe-core/playwright` (dev dependency, owner approval)
    to every e2e spec, and fail on critical or serious violations.
  - **Done when:** `make test-frontend` runs axe on each flow in the map.

### Suggested order for these findings

1. QA-01 and QA-02: stop stranding beginners.
2. QA-03, QA-04, QA-05, QA-07: errors that explain themselves.
3. BR-01 to BR-04 and DT-01: broken layouts and the lease lockout.
4. DT-07 to DT-12, FE-08: accessibility to a clean axe run.
5. QA-11, DE-01 to DE-07, DT-02 to DT-05: stability and feel.
6. FE-01 to FE-07 and the remaining BR and DT items.

## Skill-based UI audit: dark mode

This second audit ran on 2026-10-11 against `feat/dark-mode` at `651bb08`
(PR #17), which adds Auto, Light, and Dark themes on top of `main` at
`a8c8c37`. It repeats the first audit's method: map every flow, then run
the five review skills one at a time, each in light and dark. Item numbers
continue from the first audit.

How it was run:

- **Isolated instances only.** A clean export of `651bb08` was built and
  served by `tests/e2e_server.py` on port 4190 (login off) and 4191 (login
  on), with scratch storage and fake agents. Fixtures went in through the
  public API: worst-case names and projects, a failed 20,000-line log, a
  41-job fan-out, a committed diff, ANSI output, a waiting approval, and an
  untracked workflow.
- **Owner instance not used.** The instance on port 17945 still runs the
  backend started on 2026-10-09, while `relay/static` in the checkout was
  rebuilt on 2026-10-11, so it serves today's frontend against an older
  API. Restart it from the current checkout before relying on it.
- **Tools:** Playwright with Chromium, the Chrome DevTools Protocol, and
  axe-core 4.14. Themes were forced through `relay-theme-preference` and
  through emulated `prefers-color-scheme`.
- **Widths:** 320, 375, 600, 760, 900, 1024, and 1440 pixels, plus 200%
  root text size and `dir="rtl"`.
- **Limit:** agent Markdown could not be rendered live, because the test
  server's single inline worker is held by a waiting approval. Its dark
  styling was checked in `styles.css` instead (BR-16).

### Flow map, updated

The first audit's flows F01 to F32 still apply. These flows are new or
changed, and every row was exercised in both themes.

| # | Flow | Entry point | What the user does | Passes |
| --- | --- | --- | --- | --- |
| F33 | Choose a theme | Header **Theme mode** menu (System, Light, Dark); Help › **Switch to dark mode** | Pick a theme; it persists across reloads | DT, QA, DE |
| F34 | Follow the operating system | System choice; OS appearance change | Theme follows the OS live | DT, QA |
| F35 | Manage a workflow | **Manage workflow** | Rename, duplicate, disable, delete | QA, DE |
| F36 | Edit in modes | **Editor mode** (Visual, YAML, Split); Undo, Redo, **Format as YAML** | Switch views, undo, format | QA, DE |
| F37 | Workflow settings | **Workflow settings** dialog | Name, run title, launch inputs, triggers | QA, BR, FE |
| F38 | Commit new workflow files | Run workflow › **Commit workflow files** | Review, confirm, commit only those files | QA |
| F39 | Read a job and its steps | Job page › numbered step | Expand a step to read its output | BR, DE |
| F40 | Read committed changes | Job › **Changes** | Diff viewer, inline or side by side | BR |
| F41 | Help guides | Help › Getting started, Coming from GitHub Actions, Keyboard shortcuts | Read in-app guides | QA |

### browser-testing-with-devtools, dark mode

Held up: there is no flash of the wrong theme (the boot script sets
`data-theme="dark"` and the dark background before any app JavaScript
loads); System mode follows a live OS change; the console is clean; no
request fails or repeats in either theme; and no visible element in dark
mode has a bright surface or text below 3:1.

- [x] **DT-13. The browser's theme colour ignores the chosen theme.**
  - **Evidence:** `index.html` has two `theme-color` tags keyed to
    `prefers-color-scheme`, and `theme.tsx` (around line 449) only updates a
    tag without `media`. Browsers use the first matching tag, so with the
    OS on light and Relay on Dark the effective colour is `#f4f6fb`, and with
    the OS on dark and Relay on Light it is `#0f172a`. Mobile browser chrome
    shows the wrong colour.
  - **Fix:** When the preference is explicit, set every `theme-color` tag's
    `content` to the resolved colour (or remove their `media` attributes).
    Restore the media-keyed values only when the preference returns to
    System.
  - **Done when:** A test covers all six OS and preference combinations and
    checks the effective tag.

- [x] **DT-14. The workflow graph uses React Flow's grey theme, not Relay's.**
  - **Evidence:** `FlowCanvas.tsx:187` passes `colorMode`, so the dark canvas
    is `#141414` with `#2b2b2b` controls, a neutral grey inside Relay's
    blue-slate surfaces (`#0f172a`, `#1e293b`).
  - **Fix:** Set React Flow's CSS variables (`--xy-background-color`,
    controls, edges, minimap, attribution) from Relay tokens in both themes.
  - **Done when:** The canvas, controls, and edges use only Relay tokens.

- [x] **DT-15. YAML highlighting loses its structure in dark mode.**
  - **Evidence:** Dark YAML shows keys in `#e2e8f0` beside plain text in
    `#cbd5e1`, and only strings are coloured. Light YAML colours keys blue
    and strings red (`#aa1111`), and red strings read as errors.
  - **Fix:** One highlight style per theme with distinct key, string,
    number, comment, and expression colours, all at least 4.5:1, and no red
    for ordinary strings.
  - **Done when:** Keys, strings, and `${{ }}` expressions are visibly
    distinct in both themes.

### browser-qa, dark mode

#### QA report: isolated dark-mode build, 2026-10-11

##### Smoke test

- **Console:** no errors or warnings in either theme on any view.
- **Network:** no 4xx or 5xx responses; no duplicate requests.
- **Core Web Vitals:** CLS 0 on every view at 320, 375, and 1440 pixels in
  both themes. LCP was not re-measured. INP was not measured.
- **CI for PR #17:** browser-tests fails 2 of 246 tests (QA-14).

##### Interactions

- [✓] Theme menu: System, Light, Dark; choice persists after reload.
- [✓] System mode follows the OS, including a live change.
- [✓] Keyboard: the toggle is reachable by Tab, opens with Enter, changes
  with the arrow keys, and returns focus to the toggle.
- [✓] Phone: the toggle stays visible at 375 pixels.
- [✓] The YAML editor keeps unsaved text and undo history across a theme
  change.
- [✓] Sign-in page follows the OS theme.
- [✗] Form fields are invisible in dark mode (QA-13).
- [✗] Header wraps to three rows at 600 to 1,023 pixels (QA-14).
- [✗] Guided tour fails contrast in dark mode (QA-15).

##### Visual

- INCONCLUSIVE for dark mode: the 21 committed baselines are light only.
- [✗] Fields, inputs, and Markdown tables lose their outlines (QA-13,
  BR-16).

##### Accessibility

- Dark mode passes axe colour contrast on every page, menu, dialog,
  tooltip, and select, except the guided tour. `label-content-name-mismatch`
  flags path disclosures in both themes once axe 4.14 runs it by default.
- axe does not test WCAG 1.4.11 (non-text contrast), which is why QA-13
  passed every automated check.

##### Verdict: DO NOT SHIP dark mode yet

QA-13 makes every form unusable in dark mode, and QA-14 fails CI.

- [x] **QA-13. Form fields are invisible in dark mode. Blocker.**
  - **Evidence:** Text fields, selects, and text areas in dialogs and
    Settings have an outline of `rgb(30, 41, 59)` on a `rgb(30, 41, 59)`
    surface (1.00:1). Empty fields such as **Shared default model** render
    as a blank gap; filled fields read as plain text. Root cause:
    `border-subtle` and `surface` are both `#1e293b` in dark mode
    (`theme.tsx` lines 64 and 69; `styles.css` `--relay-border-subtle`), and
    `MuiOutlinedInput` uses `border-subtle`. Light mode is weak too: inputs
    are `#dce1ec` on white (1.31:1), below the 3:1 WCAG 1.4.11 minimum.
  - **Fix:** Add an input-boundary token that meets 3:1 on every surface it
    sits on: about `#748299` in dark (3.76:1 on `#1e293b`) and `#7b879c` in
    light (3.63:1 on white). Use it for outlined inputs and selects. Raise
    dark `border-subtle` to `#334155` for structural lines.
  - **Done when:** A browser test measures the outline-to-surface contrast of
    every input in dialogs and Settings at 3:1 or more in both themes.

- [x] **QA-14. The theme toggle breaks the header at tablet widths.**
  - **Evidence:** CI for PR #17 fails `control-layout.spec.ts:498` at 760
    and 900 pixels: the header is 143 pixels tall against a 116 limit.
    Measured: 143 pixels from 600 to 1,023 pixels wide; **Help** wraps onto a
    third row.
  - **Fix:** Below 1,024 pixels render the toggle as an icon button with a
    tooltip, or move the theme choice into the Help (or account) menu as a
    radio group.
  - **Done when:** The header is at most two rows from 320 to 1,023 pixels
    and the layout spec passes.

- [x] **QA-15. The guided tour fails contrast in dark mode.**
  - **Evidence:** `.relay-tour .driver-popover-next-btn` sets `color: white`
    on `var(--relay-primary)` (`#93c5fd` in dark): 1.80:1. axe also reports
    the close button at 1.06:1 and the progress text "1 of 27" at 3.04:1;
    **Back** keeps Driver.js's light default.
  - **Fix:** Use an on-primary text token (`#0f172a` on `#93c5fd` is 9.9:1)
    and style Back, close, and progress with Relay tokens in both themes.
  - **Done when:** axe passes on the tour in both themes.

- [x] **QA-16. Dark mode has no automated visual or accessibility gate.**
  - **Evidence:** `frontend/e2e/baselines/linux` holds 21 light baselines and
    no dark ones. `theme.spec.ts` contains no axe check, although commit
    `44119a7` says it asserts WCAG 2.2 AA across theme states.
  - **Fix:** Run `assertAccessible` for every view in both themes, add dark
    baselines for the visual set, and add a non-text-contrast check for
    input boundaries (QA-13), which axe does not cover.
  - **Done when:** `make test-frontend` fails if dark mode regresses visually
    or on contrast.

- [x] **QA-17. Two theme controls disagree.**
  - **Evidence:** The header menu offers System, Light, and Dark. Help also
    offers **Switch to dark mode** or **Switch to light mode**, which ignores
    System and silently replaces it with an explicit choice. The toggle's
    accessible name says "Theme mode: dark" while its menu says "Dark".
  - **Fix:** Keep one control. Remove the Help item, or make it open the same
    three-way choice. Use the same capitalised labels in names and menus.
  - **Done when:** There is one way to choose a theme, with three options.

- [x] **QA-18. Workflow settings shows the raw schema tree.**
  - **Evidence (both themes):** The dialog lists "on value type: Key/value
    table", "on key", "on.workflow_dispatch value type", and
    "on.workflow_dispatch.inputs key". The "Input task" heading overlaps the
    "Input name" label, and the "Workflow name" label is clipped at the top.
  - **Fix:** Replace the tree with a **Triggers** section (manual run with
    inputs, local triggers) in plain words. Keep the generic tree behind an
    **Advanced** disclosure, and fix the label spacing.
  - **Done when:** A beginner can add a launch input without seeing a YAML
    path.

- [x] **QA-19. Destructive and blocked actions read like ordinary ones.**
  - **Evidence:** In **Manage workflow**, **Delete** has the same style and
    position as Rename, Duplicate, and Disable. A launch blocked by an
    untracked workflow returns "The Git worktree has code or staged changes"
    with "Relay leaves workflow reports untouched", which describes neither
    the file nor the fix.
  - **Fix:** Style Delete as destructive and set it apart from the other
    actions. Say "An untracked workflow file blocks this run" and offer
    **Commit workflow files** in the error.
  - **Done when:** Delete is visually distinct, and the error names the file
    and the fix.

### break-ui, dark mode

The worst-case data from the first audit was replayed in light and dark at
320 and 1440 pixels, at 200% text size in dark, and with `dir="rtl"` in dark.

#### Part 1: What broke

| # | Severity | Field | Worst-case value | What happens | Fix |
| --- | --- | --- | --- | --- | --- |
| 1 | Broken | Every outlined input (dark) | Any form | Outline equals the surface (1.00:1); empty fields disappear | QA-13 |
| 2 | Broken | Header (both) | Width 600–1,023 pixels | Three rows, 143 pixels; Help wraps alone | QA-14 |
| 3 | Ugly | Editor workflow title (both) | 90-character name with markup and emoji | `h1` is 147 pixels (5 lines) at 320 pixels; run titles are clamped, editor titles are not | Apply the run-title clamp and full-title disclosure to the editor heading |
| 4 | Ugly | Job **Changes** commit ID (both) | 40-character SHA | Runs off-screen at 320 pixels (x up to 369) | Show 7 characters with a copy button; break the full ID anywhere |
| 5 | Ugly | Agent Markdown tables and quotes (dark) | Table, blockquote | Cell borders and the quote bar use `--relay-border-subtle` on `#1e293b`, so they vanish (from `styles.css`) | Use the raised structural border token |
| 6 | Ugly | Storage project name (both) | 72-character project name | Truncated with no tooltip or title | Add a title and the copyable full value, like paths |
| 7 | Ugly | Step panel (both) | Any job | Expanding "1. Step 1" opens a nested job view: raw `step_1` heading, a second Attempt picker, and repeated Set up and Instructions | Show the step's output directly under its row, as GitHub does |
| 8 | Fragile | Finished job **Changes** (both) | Job with no commits | "No committed code changes yet." | Say "This job committed no changes." once the job has finished |
| 9 | Fragile | Layout direction | `dir="rtl"` | "Find a project" overflows the left edge (-41 pixels) | Out of scope until RTL is supported; use logical CSS properties when touching layout |

Fix locations: `frontend/src/theme.tsx` and `frontend/src/styles.css`
(rows 1, 5), `frontend/src/AppHeader.tsx` and
`frontend/src/components/ThemeToggle.tsx` (row 2),
`frontend/src/components/WorkflowEditorHeader.tsx` (row 3),
`frontend/src/components/JobWorkspaceView.tsx` and `JobLogView.tsx`
(rows 4, 7, 8), `frontend/src/components/StorageSettings.tsx` (row 6).

- [x] **BR-12. Clamp the editor's workflow title** (row 3).
- [x] **BR-13. Shorten commit IDs in Changes** (row 4).
- [x] **BR-14. Show step output directly** (row 7). Remove the nested job
  chrome; keep attempts at the job level.
- [x] **BR-15. Fix the finished-job Changes copy and the Storage name
  tooltip** (rows 6, 8).
- [x] **BR-16. Restore Markdown table and quote borders in dark mode**
  (row 5).
- [x] **BR-17. Add the dark theme to the worst-case fixture.** Run the
  `/__test__/worst-case` screens in both themes at 320 and 1440 pixels and
  fail on horizontal scroll, clipped primary actions, or input outlines
  below 3:1.

#### Part 2: Decisions for you

- **Header theme control:** an icon button with a tooltip is recommended
  over the labelled menu button, because the label is what forces the wrap
  (QA-14).
- **ANSI black:** it renders like default text in dark mode. Keep that
  (readable) rather than true black (invisible).
- **Default theme:** keep System as the default for new users.

#### Part 3: What held up

- No flash of the wrong theme on load; System follows the OS live.
- No horizontal scroll at 320 pixels on any view in either theme.
- ANSI colours, including black, dim, and bright, measure at least 4.5:1 on
  both terminal backgrounds; diff additions and removals stay readable.
- Run titles clamp to two lines with `#number` visible in both themes.
- CLS is 0 on normal loads; a theme change causes no layout shift.
- Literal `<script>`, `&amp;`, and `**` still render as text.

### emil-design-eng, dark mode

| Before | After | Why |
| --- | --- | --- |
| Dark `border-subtle` equals `surface` (`#1e293b`) | Structural lines `#334155`; input outlines `#748299` | In dark mode boundaries come from lightness; equal values erase them |
| Dark `surface-elevated` equals `surface`; menus, tooltips, and dialogs over cards are the same `#1e293b` | Elevated `#273449` plus a 1-pixel `#334155` border | Shadows barely show on dark backgrounds, so elevation must be a lighter surface |
| React Flow canvas `#141414`, controls `#2b2b2b` | Relay slate tokens for canvas, controls, edges, minimap | A neutral grey panel inside blue-slate reads as a different material |
| Dark YAML keys `#e2e8f0` beside text `#cbd5e1`; light strings `#aa1111` | Distinct key hue per theme; strings green or teal | Syntax colour should show structure; red means error |
| Tour **Next**: white on `#93c5fd`; **Back** is Driver.js light grey | On-primary text token; secondary buttons from surface tokens | Overlays must belong to the active theme |
| Labelled "Dark ▾" button in the header | Icon button with tooltip; menu holds System, Light, Dark | A rarely used control should not cost a header row |
| Help menu repeats the theme switch as a two-way toggle | One three-way control | Two controls that disagree erode trust |
| **Delete** looks like **Rename** in Manage workflow | Destructive colour, separated, last | Dangerous actions need a different shape and place |
| Step row expands into a nested job panel | Step row expands straight to its log | Every extra layer is another click before the answer |

Held up: the theme change is instant with no animated background; focus
rings measure 8.11:1 in dark; press feedback (`scale(0.98)`), tabular
figures, and reduced-motion rules apply in both themes; hover tints are
visible but quiet.

- [x] **DE-08. Give dark mode real borders and elevation** (rows 1, 2).
- [x] **DE-09. Theme the graph, editor highlighting, and tour** (rows 3–5).
- [x] **DE-10. Make the theme control compact and single** (rows 6, 7).
- [x] **DE-11. Mark destructive actions and flatten step logs** (rows 8, 9).

### frontend-ui-engineering, dark mode

- [x] **FE-09. Keep theme tokens in one source.**
  - **Evidence:** The 26 dark tokens exist in four hand-maintained copies:
    `theme.tsx`, `:root[data-theme="dark"]` and
    `@media (prefers-color-scheme: dark)` in `styles.css`, plus colours in
    `index.html`. They agree today, but nothing enforces it; the storage key
    `relay-theme-preference` is also typed in two files.
  - **Fix:** Generate the CSS variables from the TypeScript tokens (MUI CSS
    variables or a build step), share the storage key from one module, and
    add a test that fails on drift.
  - **Done when:** Changing a token in one place updates every theme surface.

- [x] **FE-10. Split `theme.tsx` by responsibility.**
  - **Evidence:** At 537 lines it holds tokens, MUI overrides, the theme
    context, storage, media listeners, and document side effects (class,
    `color-scheme`, `theme-color`).
  - **Fix:** Separate tokens, the MUI theme factory, the provider, and a
    small `applyThemeToDocument` function with its own tests (DT-13).
  - **Done when:** Each part can be tested alone.

- [x] **FE-11. Theme third-party surfaces through adapters.**
  - **Evidence:** React Flow (DT-14), Driver.js (QA-15), and CodeMirror
    highlighting (DT-15) are each themed differently, and two of the three
    miss tokens.
  - **Fix:** One adapter per library that reads Relay tokens, with a
    dark-mode test for each.
  - **Done when:** No third-party surface uses its own default palette.

- [x] **FE-12. Document theme behaviour.**
  - **Evidence:** `docs/web-ui.md` does not mention the theme menu, System
    mode, persistence, the boot script, or `theme-color`, although AGENTS.md
    requires the behaviour reference to change with the feature. BR row 14
    of the first audit still says dark mode is ignored.
  - **Fix:** Add a **Theme** section to `docs/web-ui.md` and update the
    first audit's dark-mode row.
  - **Done when:** The docs describe every theme behaviour tested in QA-16.

### Suggested order for these findings

1. QA-13 and QA-14: usable forms and a passing CI.
2. QA-15, BR-16, DE-08: contrast and borders everywhere in dark mode.
3. DT-13, DT-14, DT-15, FE-11: browser chrome and third-party theming.
4. QA-16, BR-17, FE-09, FE-12: gates, single token source, and docs.
5. QA-17, QA-18, QA-19, BR-12 to BR-15, DE-09 to DE-11, FE-10.

## Workflow builder beginner audit

This audit ran on 2026-10-17 against `main` at `62ac59e`. It asks one
question: can someone new to Relay build or change a workflow, in the visual
editor or in YAML, without already knowing Relay's schema? A starter runs end
to end, but its approvals and its results confuse a beginner, and building or
editing a workflow is harder still. Items are grouped by category
and carry a priority: **P0** strands or misleads a beginner, **P1** slows them
down, **P2** is polish. Item numbers use the `WB` prefix.

The [implementation handoff](workflow-builder-handoff.md) specifies every
item in full, records the owner's decisions (D1 to D4) and the defaults chosen
for the rest, and gives the delivery order. Each item links to its section.

How it was run:

- **Isolated instance only.** `tests/e2e_server.py` on port 8765 with scratch
  storage and fake agents. The owner's instance and provider accounts were
  not used.
- **Validation matrix.** 51 sources (11 freshly added actions and 40 common
  mistakes) were sent to `POST /api/workflow-language/validate`, which is the
  endpoint the editor calls. Sources that validated were then saved,
  committed, and launched through `POST /api/runs` to see where each mistake
  is actually caught.
- **Browser pass.** Playwright with Chromium at 1440, 768, and 375 pixels:
  starter gallery, blank workflow, **Add job** for each type, every job tab,
  **Workflow settings**, the right-click menu, YAML completion, hover, the
  Tab key, and clearing the document. axe-core 4 ran on the editor and on
  the open job drawer.
- **End-to-end journeys.** Two features were built through the browser
  alone. The first followed the guided path: welcome slides, **Get started**,
  the default **AI coding workflow**, three approvals, and the finished run
  (`/__test__/starter-project` with `full_workflow`, whose fake agents write
  `feature.py` and `test_feature.py`). The second built a two-job workflow
  from a blank one with forms only, then saved, launched, and watched it.
  Approval answers were read from the screen, not from test code.
- **GitHub Actions comparison.** 37 sources written from GitHub Actions
  habit, including a typical CI workflow pasted verbatim, went through the
  validation endpoint; 16 validated. Five of them were launched to see
  run-time behavior. GitHub behavior was checked against its
  [workflow syntax](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-syntax)
  and [job variations](https://docs.github.com/en/actions/how-tos/write-workflows/choose-what-workflows-do/run-job-variations)
  references and the `action.yml` files of `actions/upload-artifact` and
  `actions/cache`.
- **Source and docs.** The editor components, `support_manifest()`, the
  action contracts, `docs/getting-started.md`,
  `docs/coming-from-github-actions.md`, and the authoring sections of
  `docs/web-ui.md`.
- **Not covered:** live providers, macOS and Windows, screen readers, dark
  mode, and editing the nine-job **AI coding workflow** starter visually.

What already works: seven starters with job sequences, required agents, and
input types; a blank workflow that starts valid; line-anchored server errors
with the canvas kept at the last valid version; tailored messages for GitHub
Actions habits such as `runs-on`, `permissions`, and `services`; Split view
that keeps comments; undo, redo, and draft autosave; no horizontal overflow
at 375 pixels.

### YAML editor

- [ ] **WB-01. Make completion follow the cursor position.**
  - **Priority:** P0.
  - **Spec:** [WB-01 in the handoff](workflow-builder-handoff.md#wb-01-make-completion-follow-the-cursor-position)
  - **Evidence:** `YamlEditor.tsx:61` merges every property of all 115
    schema definitions, every action input, and every context property into
    one list, whatever the cursor position. Typing `ru` under a job offers
    `run`, `run-id`, `run-name`, `relay.run_id`, `workflow_run`, and
    `relay.run_number`. Ctrl+Space after `- uses:` fills CodeMirror's
    100-option list with field names, starting with `agent`, `agents`,
    `argv`, and `artifacts`.
  - **Fix:** Resolve the YAML path at the cursor from the parsed document.
    Offer only the properties of that path's definition, action inputs only
    inside the `with:` of a known `uses:`, and context names only inside
    `${{ }}`.
  - **Done when:** A browser test checks completion at the root, a job, a
    step, an agent step's `with:`, and inside an expression, and each list
    contains only fields valid there.

- [ ] **WB-02. Suggest values, starting with action names.**
  - **Priority:** P0.
  - **Spec:** [WB-02 in the handoff](workflow-builder-handoff.md#wb-02-suggest-values-starting-with-action-names)
  - **Evidence:** Completion only offers keys. The 11 `relay/*@v1` actions in
    `manifest.builtins` are never offered after `uses:`, so a beginner must
    already know they exist. `shell`, input `type`, report `format`,
    `cache-mode`, and agent IDs have fixed values that are not offered
    either.
  - **Fix:** Add value completion for those fields, with a one-line
    description for each action. Selecting an action could insert a `with:`
    block containing its required inputs (see WB-07).
  - **Done when:** Ctrl+Space after `uses:` lists the 11 actions, and each
    fixed-value field lists its values.

- [ ] **WB-03. Give hover and completion real descriptions.**
  - **Priority:** P0.
  - **Spec:** [WB-03 in the handoff](workflow-builder-handoff.md#wb-03-give-hover-and-completion-real-descriptions)
  - **Evidence:** Only 6 of 115 definitions in the served manifest have a
    `description` (`workflow-root`, `on`, `strategy`, `steps`,
    `entrypoints`, `recovery`). Hover (`YamlEditor.tsx:103`) uses the first
    definition that contains the key, then falls back to the parent's
    description or to `key: type`. As a result:
    - `needs` reads `needs: needs`, `if` reads `if: job-if`,
      `timeout-minutes` reads `timeout-minutes: number-strategy-context`.
    - A step's `run` reads `run: workflow-defaults-run`, the description of a
      different field.
    - `name` and `env` read "Relay workflow: local jobs and ordered steps."
    - `agent`, `prompt`, `argv`, and every other action input have no hover.
      Completion describes them only as "Local action input".
  - **Fix:** Describe every definition a user can type in `schema.json`, and
    every action input next to the contracts in `builtins.py`. Resolve hover
    by YAML path, not by the first matching definition. Link each
    description to its section in [Workflows](workflows.md).
  - **Done when:** A test fails when a property reachable from
    `workflow-root`, or an action input, has no description. A hover test
    distinguishes a step's `run` from `defaults.run`.

- [ ] **WB-04. Make Tab indent in the YAML editor.**
  - **Priority:** P1.
  - **Spec:** [WB-04 in the handoff](workflow-builder-handoff.md#wb-04-make-tab-indent-in-the-yaml-editor)
  - **Evidence:** The editor uses `basicSetup` without `indentWithTab`.
    Pressing Tab in the YAML editor changes nothing, and focus leaves the
    editor for the page body. YAML forbids tabs for indentation, so beginners
    rely on an editor that indents for them.
  - **Fix:** Bind `indentWithTab` with a two-space indent unit, following
    CodeMirror's Tab example. CodeMirror's tab focus mode keeps a keyboard
    exit: Escape then Tab within two seconds, or Ctrl+M (Shift+Alt+M on
    macOS) to toggle. Document both in
    [Keyboard shortcuts](keyboard-shortcuts.md).
  - **Done when:** A browser test checks that Tab indents by two spaces,
    Shift+Tab outdents, and Escape followed by Tab moves focus out of the
    editor.

- [ ] **WB-05. Explain an empty YAML document.**
  - **Priority:** P1.
  - **Spec:** [WB-05 in the handoff](workflow-builder-handoff.md#wb-05-explain-an-empty-yaml-document)
  - **Evidence:** After selecting all and deleting, the page still shows
    "Validating workflow…" 10 seconds later, and the canvas shows loading
    placeholders. No error explains the state. The validation effect returns
    early for empty text (`useActionsWorkflowWorkspace.tsx:331`), and the
    endpoint rejects it anyway ("yaml must be a non-empty string.").
  - **Fix:** Treat an empty draft as invalid with a message such as "This
    workflow is empty. Restore the saved source or add a job." End the
    loading state.
  - **Done when:** A browser test clears the document and sees that message
    in both Visual and YAML modes.

### Visual editor

- [ ] **WB-06. Keep the command form and the YAML in agreement.**
  - **Priority:** P0.
  - **Spec:** [WB-06 in the handoff](workflow-builder-handoff.md#wb-06-keep-the-command-form-and-the-yaml-in-agreement)
  - **Evidence:** `ActionCommandFields.tsx:40` displays
    `inputs.argv ?? '["echo","Ready"]'` but never writes that value. Adding
    a command job writes `with: {}`, so the form shows `echo` and `Ready`
    while the banner says "relay/command@v1 requires exactly one of argv or
    command." and the canvas falls back to "Showing the last valid version".
    An `argv` that is not valid JSON is displayed as an empty list.
  - **Fix:** Write the default into the document when the step is created,
    or show empty fields with placeholder text. Show a parse error for an
    unparsable `argv` instead of an empty list.
  - **Done when:** A test adds a command job and checks that the form, the
    YAML, and validation agree.

- [ ] **WB-07. Make newly added jobs and steps valid.**
  - **Priority:** P0.
  - **Spec:** [WB-07 in the handoff](workflow-builder-handoff.md#wb-07-make-newly-added-jobs-and-steps-valid)
  - **Evidence:** **Add job** (`useActionsWorkflowWorkspace.tsx:547`) and the
    **Step type** menu (`ActionJobSteps.tsx:84`) fill only an action's
    required inputs, using empty strings. A fresh `command`, `loop`, or
    `validate-report` step fails validation immediately. A fresh
    `human-wait` step validates with an empty question. A fresh `agent` step
    is `with: {}`.
  - **Fix:** Give each action a valid starting configuration, or open a
    short setup form that focuses the missing fields. `loop` needs a picker
    for an existing reusable workflow rather than an empty path.
  - **Done when:** For each of the 11 actions, **Add job** and **Step type**
    produce a source that passes validation, or the form says which field to
    fill.

- [ ] **WB-08. Let Add step choose the step type.**
  - **Priority:** P1.
  - **Spec:** [WB-08 in the handoff](workflow-builder-handoff.md#wb-08-let-add-step-choose-the-step-type)
  - **Evidence:** **Add step** (`ActionJobSteps.tsx:263`) always appends
    `run: echo Ready`; the user must then change its type. BX-07 promised
    that built-in actions are exposed through **Add step**.
  - **Fix:** Make **Add step** a menu: Agent, Script, Command, Approval,
    Check a report, Upload artifact, and More.
  - **Done when:** A browser test adds each listed type in one action.

- [ ] **WB-09. Show a job's steps as a list.**
  - **Priority:** P1.
  - **Spec:** [WB-09 in the handoff](workflow-builder-handoff.md#wb-09-show-a-jobs-steps-as-a-list)
  - **Evidence:** The drawer edits one step at a time through an **Ordered
    step** select (`ActionJobSteps.tsx:54`). Canvas cards show the job and a
    single summary, for example "work · Agent · m1" or "relay/command@v1".
    Six of the seven starters have one job, so their canvas shows one box
    and none of the steps.
  - **Fix:** Show an ordered step list with type icons, names, and drag or
    move controls in the drawer, and list step names on each card.
  - **Done when:** A user can see and reorder every step of a job without
    opening a select.

- [ ] **WB-10. Describe step types in plain words.**
  - **Priority:** P1.
  - **Spec:** [WB-10 in the handoff](workflow-builder-handoff.md#wb-10-describe-step-types-in-plain-words)
  - **Evidence:** **New job type** and **Step type** list bare slugs:
    `agent`, `cache`, `command`, `download-artifact`, `human-wait`, `loop`,
    `restore-cache`, `save-cache`, `upload-artifact`, `validate-input`, and
    `validate-report`. The **Action reference** field below **Step type**
    (`ActionJobSteps.tsx:123`) repeats the same choice as raw text.
  - **Fix:** Use labels from the vocabulary map (for example, **Approval**
    for `human-wait`), add a one-line description, and group them: Agents,
    Scripts and commands, Approvals, Reports, Artifacts and caches,
    Advanced. Keep **Action reference** under Advanced for local `./`
    actions.
  - **Done when:** Every menu entry has a label and a description, and no
    slug appears outside Advanced.

- [ ] **WB-11. Lead with the basics in job and step forms.**
  - **Priority:** P1.
  - **Spec:** [WB-11 in the handoff](workflow-builder-handoff.md#wb-11-lead-with-the-basics-in-job-and-step-forms)
  - **Evidence:**
    - The **General** tab, which opens first, shows the condition with its
      expression builder, timeout, **Reusable workflow**, matrix axes and
      include (each with **Advanced JSON**), and concurrency. Steps are on
      the second tab.
    - An agent step's first control is **Advanced JSON: Action inputs**
      (`ActionBuiltinFields.tsx:78`).
    - Command arguments show type selectors for every item ("Program and
      arguments value type: List", "item 1 value type: Text or expression").
  - **Fix:** Open new jobs on **Steps**. Move matrix, concurrency, reusable
    workflow, **Advanced JSON**, and value-type selectors under an
    **Advanced** section. Show a value-type selector only when the value is
    not plain text.
  - **Done when:** A new job's drawer shows only name, start after, and steps
    until **Advanced** is opened.

- [ ] **WB-12. Use one control for the agent choice.**
  - **Priority:** P1.
  - **Spec:** [WB-12 in the handoff](workflow-builder-handoff.md#wb-12-use-one-control-for-the-agent-choice)
  - **Evidence:** The **Agent** select (`ActionBuiltinFields.tsx:88`) is blank
    whenever a step uses an `agents` list, which six of the seven starters
    do. The list itself is in **Agent order** (`ActionBuiltinFields.tsx:256`),
    below the prompt editors.
  - **Fix:** Replace both with one **Runs on** control that picks a single
    agent or an ordered fallback list, and shows the effective choice,
    including saved defaults.
  - **Done when:** Opening any starter's agent step shows which agents it
    will try, in order, in one place.

- [ ] **WB-31. Show job names, not only IDs, when connecting jobs.**
  - **Priority:** P1.
  - **Spec:** [WB-31 in the handoff](workflow-builder-handoff.md#wb-31-show-job-names-not-only-ids-when-connecting-jobs)
  - **Evidence:** In the second journey the blank workflow's job was renamed
    **Review**, but **Start after** on the next job offered only `check`, its
    ID. The added job stayed `job_1` in the YAML after being named **Test**.
    The finished run's artifact table then listed `REVIEW.md` under the jobs
    "Check" and "Job 1".
  - **Fix:** Label **Start after** choices as "Review (`check`)". When a job
    is created or first named, offer to derive its ID from the name. Use job
    names in the artifact **Job** column.
  - **Done when:** A user who only types job names never sees a generated ID
    in the editor or the run's artifact table.

- [ ] **WB-32. Mark agents that are not installed.**
  - **Priority:** P2.
  - **Spec:** [WB-32 in the handoff](workflow-builder-handoff.md#wb-32-mark-agents-that-are-not-installed)
  - **Evidence:** With only Codex installed, the agent step's **Agent** select
    listed Codex, Claude Code, GitHub Copilot CLI, Cursor CLI, and
    Antigravity with no status, although the **Get started** checklist marks
    such agents "Not installed".
  - **Fix:** Show the checklist's status in the select and disable agents
    that are not installed, with a link to the checklist.
  - **Done when:** An agent that cannot run is visibly marked wherever it can
    be chosen.

- [ ] **WB-33. Keep canvas cards in view after the drawer closes.**
  - **Priority:** P2.
  - **Spec:** [WB-33 in the handoff](workflow-builder-handoff.md#wb-33-keep-canvas-cards-in-view-after-the-drawer-closes)
  - **Evidence:** After adding a second job and closing its drawer, both
    cards sat cut off at the left edge of the canvas with their labels
    hidden. The canvas follows the selected job while the drawer is open
    (`followSelection` in `WorkflowCanvas.tsx`), which is the likely cause.
  - **Fix:** Fit the view to the graph when the drawer closes, or keep the
    selected card centred in the uncovered area.
  - **Done when:** A browser test adds a job, closes the drawer, and finds
    every card fully inside the canvas.

### Validation and error messages

- [ ] **WB-13. Name the field and suggest the closest match.**
  - **Priority:** P0.
  - **Spec:** [WB-13 in the handoff](workflow-builder-handoff.md#wb-13-name-the-field-and-suggest-the-closest-match)
  - **Evidence:**
    - `prmpt:` in an agent step reports "relay/agent@v1 has missing
      required or unknown action inputs." (`builtins.py:49`) without naming
      `prmpt`.
    - `stpes:` reports "steps: Required field is missing." before
      "stpes: Unknown workflow field.". `rnu:` and `Jobs:` behave the same
      way.
  - **Fix:** Name each unknown and missing input. Suggest the nearest allowed
    key ("Did you mean `steps`?"). Report the unknown key before the missing
    key it causes.
  - **Done when:** Tests cover a misspelled root, job, step, and action-input
    key.

- [ ] **WB-14. Accept one value per line for list inputs.**
  - **Priority:** P0. **Decided** (D1): accept a JSON array string or one value
    per line; YAML sequences stay rejected.
  - **Spec:** [WB-14 in the handoff](workflow-builder-handoff.md#wb-14-accept-one-value-per-line-for-list-inputs)
  - **Evidence:** `agents: [codex, claude]`, `argv: [git, status]`, and
    `options: [yes, no]` each report "Expected a scalar string.". Starters
    and docs write `'["codex", "claude"]'`, and
    [Coming from GitHub Actions](coming-from-github-actions.md) shows
    `options: '["Approve", "Reject"]'` without explaining why.
  - **Fix:** Accept one item per line, as Relay already does for `path`,
    `prompt-files`, and `restore-keys`, while JSON array strings keep
    working. GitHub Actions users already write lists this way, because
    GitHub's grammar, which Relay's schema copies, types `with` values as
    strings. A YAML sequence gets a message naming both accepted forms.
  - **Done when:** Each of the three inputs works in both forms, and a YAML
    list gets the new message, with a test for each input.

- [ ] **WB-15. Catch literal mistakes while editing, not mid-run.**
  - **Priority:** P0.
  - **Spec:** [WB-15 in the handoff](workflow-builder-handoff.md#wb-15-catch-literal-mistakes-while-editing-not-mid-run)
  - **Evidence:** Each source below validated, saved, and was committed on
    the isolated server:
    - `argv: git status` launched, then the step failed with "Command argv
      must be a JSON argument vector." (`relay/execution/nodes/actions.py:900`).
    - `shell: zsh` launched, then the step failed with "A custom shell must
      contain exactly one {0} script placeholder."
      (`relay/execution/action_files.py:263`).
    - `prompt-files: prompts/missing.md` was refused at launch: "Local prompt
      'prompts/missing.md' does not exist."
    - `agent: chatgpt` was refused at launch: "Agent 'chatgpt' is outside
      Relay's Phase 1 compatibility scope."
  - **Fix:** In editor validation, parse a literal `argv` as JSON (as
    `human_wait_options` already does for `options`), check a literal shell
    name or `{0}` placeholder, check that literal local prompt files exist,
    and check literal agent IDs against the supported providers. These are
    read-only checks; keep the existing runtime checks.
  - **Done when:** Each source above shows a line-anchored error in the
    editor, and the runtime checks remain covered.

- [ ] **WB-16. Warn about references to names that do not exist.**
  - **Priority:** P1.
  - **Spec:** [WB-16 in the handoff](workflow-builder-handoff.md#wb-16-warn-about-references-to-names-that-do-not-exist)
  - **Evidence:** `${{ inputs.task }}` with no `task` input,
    `${{ steps.nope.outputs.x }}`, and `${{ needs.b.outputs.x }}` without
    `needs: b` all validate. The first two also launched and succeeded;
    missing properties yield the empty value. An agent step with neither
    `prompt` nor `prompt-files` also validated, and its run succeeded. BX-33
    promised that invalid references show the server's error inline.
  - **Fix:** Report these as warnings rather than errors, to keep GitHub
    Actions' empty-value semantics. Add a warning severity to diagnostics;
    `YamlEditor.tsx` currently marks everything as an error.
  - **Done when:** Each case shows a warning in the editor and still
    launches.

- [ ] **WB-17. List the valid choices in errors.**
  - **Priority:** P1.
  - **Spec:** [WB-17 in the handoff](workflow-builder-handoff.md#wb-17-list-the-valid-choices-in-errors)
  - **Evidence:**
    - `type: text` on a dispatch input reports "Expected one of string."
      The schema allows string, boolean, number, environment, and choice,
      but `language.py:269` reports only the first `one-of` branch.
    - `uses: relay/agent`, `relay/agent@v2`, and `actions/checkout@v4` all
      report "Only frozen local and versioned relay actions are supported."
      without listing them.
    - `if: inputs.x == "y"` reports "Unexpected expression symbol." without
      saying that strings use single quotes.
    - A step with both `run` and `uses` reports "run: Unknown workflow
      field."; a step with neither reports "run: Required field is
      missing."
  - **Fix:** Merge the constants of `one-of` alternatives into one list.
    List the actions and suggest the closest. Say "Use single quotes for
    strings" for a double-quoted literal. Say "A step needs either run or
    uses" for both step-shape errors.
  - **Done when:** Tests assert each message above.

- [ ] **WB-18. Give every diagnostic a location.**
  - **Priority:** P2.
  - **Spec:** [WB-18 in the handoff](workflow-builder-handoff.md#wb-18-give-every-diagnostic-a-location)
  - **Evidence:** A duplicate YAML key and "with.workflow: Loop requires a
    static reusable workflow." arrive without a line. `YamlEditor.tsx` then
    underlines line 1 (`Number(item.context?.line) || 1`), which points at
    the wrong place.
  - **Fix:** Attach a line and column to these errors. When none is known,
    show the banner without underlining line 1.
  - **Done when:** No diagnostic in the WB validation matrix lacks a line,
    and an unlocated diagnostic underlines nothing.

### Help, docs, and vocabulary

- [ ] **WB-19. Add help buttons to job and step controls.**
  - **Priority:** P1.
  - **Spec:** [WB-19 in the handoff](workflow-builder-handoff.md#wb-19-add-help-buttons-to-job-and-step-controls)
  - **Evidence:** In the job and step editor, only the agent effort select
    (`AgentConfiguration.tsx:130`) has a help button. The **General**,
    **Outputs**, **Environment**, and **When it fails** tabs, the step
    fields, **Workflow settings**, and the canvas have none.
    [Local web runtime](web-ui.md#get-started) says question-mark buttons
    sit beside workflow controls.
  - **Fix:** Add a help button to each field, reusing the descriptions from
    WB-03, or correct the documentation.
  - **Done when:** Every field in the job drawer and **Workflow settings**
    has help, and a browser test checks a sample from each tab.

- [ ] **WB-20. Write a "Build your first workflow" guide.**
  - **Priority:** P1.
  - **Spec:** [WB-20 in the handoff](workflow-builder-handoff.md#wb-20-write-a-build-your-first-workflow-guide)
  - **Evidence:** [Getting started](getting-started.md) (18 lines) covers
    running a starter, not editing one. There is no reference table of the
    11 actions with their purpose, required inputs, and outputs;
    [Workflows](workflows.md) describes them in prose.
  - **Fix:** Add a guide that adds a job, an agent step, and a test command,
    connects them, saves, runs, and fixes one validation error. Add an
    action table derived from the action contracts and checked by
    `scripts/check_workflow_examples.py`. Link both from the Help menu.
  - **Done when:** A new user can follow the guide end to end on a
    disposable repository.

- [ ] **WB-21. Use the YAML words in the gallery.**
  - **Priority:** P2.
  - **Spec:** [WB-21 in the handoff](workflow-builder-handoff.md#wb-21-use-the-yaml-words-in-the-gallery)
  - **Evidence:** Gallery cards show inputs such as "test_runner (enum)" and
    "agent (enum)", while the YAML says `type: choice`; `compiler.py:58`
    maps `choice` to an internal `enum`. `docs/web-ui.md` says each card
    shows a "job graph preview"; it is a line of job names joined by arrows.
  - **Fix:** Show `choice` in gallery metadata, and describe the preview as
    a job sequence.
  - **Done when:** No gallery text uses an internal type name.

- [ ] **WB-22. Label starter size and requirements.**
  - **Priority:** P2. **Decided** (D3): keep **AI coding workflow**
    preselected.
  - **Spec:** [WB-22 in the handoff](workflow-builder-handoff.md#wb-22-label-starter-size-and-requirements)
  - **Evidence:** The gallery and the checklist preselect **AI coding
    workflow**, which has nine jobs (six phases on its card) and four
    inputs, and requires "A coding agent and Claude Code with an Opus
    model". **Ask an agent** needs one agent and one input.
  - **Fix:** Label every starter with its job and approval counts, for
    example "1 job" and "9 jobs · 3 approvals", and say under the default
    card what it needs and which smaller starter to choose instead.
  - **Done when:** Every card shows its size, and the default card says what
    it needs.

### First run and results

- [ ] **WB-24. Offer approval answers as buttons.**
  - **Priority:** P0.
  - **Spec:** [WB-24 in the handoff](workflow-builder-handoff.md#wb-24-offer-approval-answers-as-buttons)
  - **Evidence:** The default starter's three approvals are free-text
    `relay/human-wait@v1` steps without `options`, each followed by a
    `relay/validate-input@v1` enum check (`ai-coding-workflow.yaml:71-83`).
    The cards ask for "Reply IMPLEMENT", then "Reply FOLLOWUP" or "Reply
    TESTS", then "Reply ACCEPT". Answering the first one with `yes` failed the
    run with "Workflow validation failed: - input 'value' must be one of the
    declared enum values", and all five later jobs were skipped. **Re-run
    failed jobs** offered only "Implement · Step 2", the check rather than
    the question, and the step page said neither what was typed nor what was
    expected.
  - **Fix:** Pass the allowed answers as `options` so the card shows buttons
    and a wrong word cannot be sent. Where free text stays, check the answer
    in the card before accepting it, and name the expected answers in any
    later failure.
  - **Done when:** Each starter approval offers buttons, and a browser test
    shows that no answer can fail the run.

- [ ] **WB-25. Show the code a finished run produced.**
  - **Priority:** P0.
  - **Spec:** [WB-25 in the handoff](workflow-builder-handoff.md#wb-25-show-the-code-a-finished-run-produced)
  - **Evidence:** After the guided run succeeded, its summary said "Work is
    complete. Review the saved documents and code changes below.", but
    **Review material** offered only five early planning documents and no
    **Committed code changes**. The run had 320 visible artifacts; the page
    loads the first 50, oldest first (`useRunWorkspace.tsx:237`), and
    decides whether changes exist from that page alone
    (`RunReviewShared.tsx:99`). The first non-empty `commits` record was the
    74th. The summary also read "Artifacts 50"
    (`RunSummaryOverview.tsx:75` counts loaded records). Meanwhile
    `GET /api/runs/{id}/changes` returned the diff for `feature.py` and
    `test_feature.py`. During the first approval the same control defaulted
    to `INITIAL_OPUS_PLANNING_PROMPT.md`
    (`RunReviewShared.tsx:111` picks the first loaded document), although the
    request named three other documents.
  - **Fix:** Decide whether changes exist from the run, not from a loaded
    page, show the server's artifact total, and default to the documents the
    request names or else the newest.
  - **Done when:** A run with more than 50 artifacts shows **Committed code
    changes** and its true artifact count without **Load more artifacts**.

- [ ] **WB-26. Say where the code is and how to take it.**
  - **Priority:** P1.
  - **Spec:** [WB-26 in the handoff](workflow-builder-handoff.md#wb-26-say-where-the-code-is-and-how-to-take-it)
  - **Evidence:** The guided run committed `feature.py` and `test_feature.py`
    to `relay/run/<run id>`; `main` was unchanged, as Relay's rules require.
    The finished page names neither that branch nor the changed files, and
    never mentions merging. Its summary shows the source commit and `main`.
  - **Fix:** Add a result line such as "2 files changed on branch
    `relay/run/…`", with the commands to inspect and merge it, and point to
    the **merge on success** option for the next run.
  - **Done when:** A user can bring a finished run's code into their branch
    without reading the docs.

- [ ] **WB-27. Say plainly that the default starter pushes and opens a pull
  request.**
  - **Priority:** P1.
  - **Spec:** [WB-27 in the handoff](workflow-builder-handoff.md#wb-27-say-plainly-that-the-default-starter-pushes-and-opens-a-pull-request)
  - **Evidence:** The starter's prompts tell the agent to push the branch and
    create a pull request with GitHub CLI when none exists
    (`01_initial_exploration_any_model.md:548-551`). The first approval
    mentions this only as "commits, push, and PR creation when missing",
    next to "the locked implementation". The second asks for "explicit
    RESOLVE and verified GitHub Viewed state" and an "explicit AGREE" per
    follow-up item.
  - **Fix:** State on the starter card and in the first approval that the
    agent will push and open a pull request if the repository has a remote.
    Rewrite the approval texts in plain words, and consider a local-only
    input.
  - **Done when:** A beginner can tell before approving what will leave
    their computer.

- [ ] **WB-28. Use display names in run views.**
  - **Priority:** P2.
  - **Spec:** [WB-28 in the handoff](workflow-builder-handoff.md#wb-28-use-display-names-in-run-views)
  - **Evidence:** While queued, the guided run's sidebar listed `refine_plan`,
    `implement`, `review`, `refresh`, `human_review`, `tests`, and
    `final_review`, plus loop scopes labelled `iteration` and `cycle` ("Step
    1 › Iteration 1"). The job count changed from 9 to 11 to 15 as loop
    scopes appeared. Commit messages read "Relay: complete job cycle". The
    artifact table repeats one file once per scope, for example
    `INITIAL_OPUS_PLANNING_PROMPT.md` under "Step 1", "Explore", "Read", and
    "Instruction".
  - **Fix:** Show each job's display name from launch, group loop scopes
    under their job, count jobs consistently, and collapse repeated
    artifacts to the latest copy, with the others under details.
  - **Done when:** No generated scope name appears in the default run view.

- [ ] **WB-29. Keep the Get started prompt after the slides close.**
  - **Priority:** P2. **Decided** (D4): keep the banner.
  - **Spec:** [WB-29 in the handoff](workflow-builder-handoff.md#wb-29-keep-the-get-started-prompt-after-the-slides-close)
  - **Evidence:** Pressing Escape on the welcome slides also removed the
    **Get started** banner behind them, as
    [Local web runtime](web-ui.md#get-started) documents. The checklist then
    lives only under the account menu.
  - **Fix:** Keep the banner until the checklist is opened or the banner is
    dismissed on its own.
  - **Done when:** Skipping the slides still leaves one visible next step.

- [ ] **WB-30. Explain the optional commit in the launch dialog.**
  - **Priority:** P2.
  - **Spec:** [WB-30 in the handoff](workflow-builder-handoff.md#wb-30-explain-the-optional-commit-in-the-launch-dialog)
  - **Evidence:** For a new workflow the dialog said "Project files are ready
    to run. 1 allowed file" and still offered **Commit workflow files**,
    which opens a separate confirmation. Nothing says whether committing is
    needed.
  - **Fix:** Label it as optional, explain what "allowed file" means, or
    hide the button when the run can start without it.
  - **Done when:** A user can tell from the dialog alone whether to commit
    before running.

### Coming from GitHub Actions

Much carries over unchanged and validated as written: `jobs`, `steps`,
`needs`, `if` with `success()`, `failure()`, and `always()`, `env`, job and
step outputs, static matrices with `include` and `exclude`,
`timeout-minutes`, `continue-on-error`, `defaults.run`, `workflow_dispatch`
inputs including `choice`, `workflow_call`, `schedule`, `push` filters,
`concurrency`, and `environment`. Default shells match GitHub's (`bash -e`,
or `bash --noprofile --norc -eo pipefail` when named; `pwsh` on Windows),
and expressions use GitHub's own grammar and fixtures. The gaps below are
where that familiarity stops, usually without saying so.

- [ ] **WB-34. Point `github` and `runner` expressions to their Relay
  names.**
  - **Priority:** P0.
  - **Spec:** [WB-34 in the handoff](workflow-builder-handoff.md#wb-34-point-github-and-runner-expressions-to-their-relay-names)
  - **Evidence:** `${{ github.sha }}`, `github.ref_name`, `github.event_name`,
    `github.workspace`, `github.actor` in `run-name`, `github.workflow` in a
    concurrency group, and `github.event.inputs.task` all report
    "Unrecognized named-value: github."; `runner.os` reports the same for
    `runner`. The replacements exist: `relay` offers `sha`, `ref_name`,
    `event_name`, `workspace`, `actor`, and `workflow`, and `host` offers
    `os`. Nearly every GitHub workflow uses at least one of these.
  - **Fix:** Replace the bare error with the Relay name, for example "Use
    `relay.sha`", and suggest `inputs.task` for `github.event.inputs.task`.
    Add the mapping to completion (WB-01).
  - **Done when:** Each `github.*` and `runner.*` property that has a Relay
    equivalent produces a message naming it.

- [ ] **WB-35. Reject the GitHub file variables in scripts.**
  - **Priority:** P0. **Decided** (D2): a hard validation error; no warning,
    no alias, and messages name only the `RELAY_*` variable.
  - **Spec:** [WB-35 in the handoff](workflow-builder-handoff.md#wb-35-reject-the-github-file-variables-in-scripts)
  - **Evidence:** A job that sets an output with
    `echo "version=1.2.3" >> "$GITHUB_OUTPUT"` validated, launched, and
    failed with "script.sh: line 1: : No such file or directory"; the
    dependent job was skipped. `$GITHUB_ENV` failed the same way. The same
    workflow using `$RELAY_OUTPUT` succeeded. The
    [language audit](workflow-language-compatibility.md) records that no
    `GITHUB_*` alias is provided, but nothing tells the user.
  - **Fix:** Fail validation when a `run` script names `GITHUB_OUTPUT`,
    `GITHUB_ENV`, `GITHUB_PATH`, `GITHUB_STATE`, or `GITHUB_STEP_SUMMARY`,
    naming the `RELAY_*` variable to use. Treat `RELAY_*` as the only names
    that have ever existed.
  - **Done when:** Each of the five names is a validation error naming its
    `RELAY_*` variable.

- [ ] **WB-36. Say what replaces each common GitHub action.**
  - **Priority:** P1.
  - **Spec:** [WB-36 in the handoff](workflow-builder-handoff.md#wb-36-say-what-replaces-each-common-github-action)
  - **Evidence:** `actions/checkout@v4`, `actions/setup-python@v5`,
    `actions/upload-artifact@v4`, `actions/cache@v4`, `docker://alpine:3.20`,
    and `./.github/actions/setup` all report "Only frozen local and
    versioned relay actions are supported.". Yet checkout is unnecessary,
    because jobs already run in a copy of the repository.
    `relay/upload-artifact@v1` and `relay/cache@v1` accept the same core
    inputs (`name`, `path`, `retention-days`; `key`, `path`,
    `restore-keys`), and local actions work under `./.relay/actions/`
    (`language.py:388`). In a file with two rejected actions, both errors
    name `steps[0]`; the second is `steps[1]` on the reported line.
  - **Fix:** Give specific guidance: remove checkout, use the installed
    toolchain instead of `setup-*`, switch to the matching `relay/*@v1`
    action, or move local actions to `./.relay/actions/`. Otherwise list the
    built-in actions (WB-17). Report each step's real index.
  - **Done when:** Each action above produces its specific guidance with the
    correct step path.

- [ ] **WB-37. Help an existing GitHub workflow become a Relay workflow.**
  - **Priority:** P1.
  - **Spec:** [WB-37 in the handoff](workflow-builder-handoff.md#wb-37-import-an-existing-github-workflow)
  - **Evidence:** A typical 15-line CI file (`push` and `pull_request`,
    `runs-on`, checkout, `setup-python`, two `run` steps) produced four
    errors. Removing those four things (six lines) made it valid; the `run`
    steps needed no change. The `runs-on` message says "select an agent in
    the step", which misleads for a job that only runs tests. Relay reads only
    `.relay/workflows/`; nothing imports from `.github/workflows/`.
  - **Fix:** Offer **Import from GitHub Actions**: copy a chosen
    `.github/workflows` file, remove or translate the known fields, and show
    what changed before saving. Reword `runs-on`: "Jobs run on this
    computer. Remove `runs-on`. To have an AI agent do the work, add a
    `relay/agent@v1` step."
  - **Done when:** Importing the CI file above yields a valid workflow and a
    list of every change made.

- [ ] **WB-38. Answer every unsupported trigger the same way.**
  - **Priority:** P2.
  - **Spec:** [WB-38 in the handoff](workflow-builder-handoff.md#wb-38-answer-every-unsupported-trigger-the-same-way)
  - **Evidence:** `on: pull_request_target` reports "Expected one of
    workflow_dispatch, workflow_call, schedule, push, repository_dispatch,
    workflow_run.", but `pull_request:` inside an `on:` mapping reports only
    "workflow.on.pull_request: Unknown workflow field." on the line after
    it.
  - **Fix:** List the supported events for both forms, say that pull
    request events have no local equivalent, and point at the key's own
    line.
  - **Done when:** The scalar, list, and mapping forms of an unsupported
    event produce the same message on the right line.

- [ ] **WB-39. Explain how to build a matrix from an expression.**
  - **Priority:** P2. Default (D5): message only.
  - **Spec:** [WB-39 in the handoff](workflow-builder-handoff.md#wb-39-explain-how-to-build-a-matrix-from-an-expression)
  - **Evidence:** `matrix: {v: ${{ fromJSON('["a","b"]') }}}` reports "A
    matrix axis must be a nonempty sequence.". GitHub documents this form,
    for example `color: ${{ fromJSON(needs.define-matrix.outputs.colors) }}`.
    Relay documents only a whole-object dynamic matrix
    ([Workflows](workflows.md#matrix-jobs)).
  - **Fix:** Say "To build the matrix from an expression, set the whole
    matrix: `matrix: ${{ fromJSON(...) }}`". Per-axis expressions are not
    added.
  - **Done when:** The message shows the accepted form.

- [ ] **WB-40. Warn about secrets that are never bound.**
  - **Priority:** P1. Default (D6): one generic warning for every name.
  - **Spec:** [WB-40 in the handoff](workflow-builder-handoff.md#wb-40-warn-about-secrets-that-are-never-bound)
  - **Evidence:** `GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}` validated and ran.
    The step printed "token length 0", and the run succeeded. Relay issues
    no GitHub token
    ([language audit](workflow-language-compatibility.md)), so a GitHub user
    gets an empty credential with no warning.
  - **Fix:** At launch, warn about each referenced secret without a binding,
    `GITHUB_TOKEN` included, and say where to add it.
  - **Done when:** Launching with an unbound secret shows a warning naming
    it.

- [ ] **WB-41. Complete the GitHub Actions mapping in the guide.**
  - **Priority:** P1.
  - **Spec:** [WB-41 in the handoff](workflow-builder-handoff.md#wb-41-complete-the-github-actions-mapping-in-the-guide)
  - **Evidence:** [Coming from GitHub Actions](coming-from-github-actions.md)
    maps eight concepts. It omits `github` to `relay`, `runner` to `host`,
    the `RELAY_*` file variables, checkout and `setup-*`, the artifact
    and cache actions, `.github/workflows` to `.relay/workflows`, local
    action paths, unsupported pull request events, and list inputs.
  - **Fix:** Add those rows, with a before-and-after version of the CI file
    from WB-37. Check the examples with
    `scripts/check_workflow_examples.py`.
  - **Done when:** Every GitHub construct named in WB-34 to WB-40 appears in
    the guide with its Relay equivalent or "not supported".

### Accessibility

- [ ] **WB-23. Name the job settings drawer.**
  - **Priority:** P2.
  - **Spec:** [WB-23 in the handoff](workflow-builder-handoff.md#wb-23-name-the-job-settings-drawer)
  - **Evidence:** axe-core 4 reports `aria-dialog-name` (serious) on the job
    settings drawer, an MUI `role="dialog"` with no `aria-label` or
    `aria-labelledby`. The editor page itself has no violations. BX-31
    requires no serious axe issues.
  - **Fix:** Point `aria-labelledby` at the **Job settings** heading and
    include the job name.
  - **Done when:** axe passes with the drawer open, and browser tests find
    the drawer by its name.

### Suggested order for these findings

1. WB-24, WB-25: a first run cannot fail on a typed word, and its result is
   visible.
2. WB-06, WB-07, WB-15, WB-35: the editor stops saying one thing while the
   workflow does another.
3. WB-34, WB-36, WB-37, WB-40, WB-41: a GitHub Actions user knows what to
   change.
4. WB-26, WB-27, WB-31: the user knows where the code is, what leaves their
   computer, and which job is which.
5. WB-01, WB-02, WB-03, WB-13, WB-14: YAML help and errors that teach the
   schema.
6. WB-08 to WB-12 and WB-19: a visual editor that starts simple.
7. WB-04, WB-05, WB-16, WB-17, WB-20: keyboard, empty state, warnings, and
   the guide.
8. WB-18, WB-21 to WB-23, WB-28 to WB-30, WB-32, WB-33, WB-38, WB-39.
