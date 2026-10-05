# Relay TODO

Only the coordinating assistant edits this file. Relay workflow agents report
proposed TODO entries without modifying it.

## Agent configuration

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

- [x] Make Relay intuitive for first-time users. Guide them through choosing a
  project and workflow, starting work, reviewing requests, and resuming a run.
  Use everyday language and clear next actions so common tasks do not require
  understanding YAML, internal node names, JSON, or status codes.
- [x] Keep advanced configuration and diagnostics in clearly labeled optional
  views. Explain what actions do and what happens next before starting,
  stopping, or approving work. Preserve explicit human review and permission
  decisions.

## Run navigation

- [x] Explain the workflow editor and run monitor in the navigation. Show the
  selected project, workflow, and run together so the owner can identify the
  work being inspected.
- [x] Show the current stage, completed work, and next action in plain language
  above the graph and logs. Make waiting and failed stages easy to find without
  reading internal node names or zooming around the graph.
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
