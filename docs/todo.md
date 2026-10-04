# Relay TODO

Only the coordinating assistant edits this file. Relay workflow agents report
proposed TODO entries without modifying it.

## Agent configuration

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

## Run navigation

- [ ] Explain the workflow editor and run monitor in the navigation. Show the
  selected project, workflow, and run together so the owner can identify the
  work being inspected.
- [ ] Show the current stage, completed work, and next action in plain language
  above the graph and logs. Make waiting and failed stages easy to find without
  reading internal node names or zooming around the graph.
- [ ] At a human review gate, show the review documents or diff, the required
  review steps, and the expected response beside the response field. Keep human
  approval distinct from automated checks and agent permission requests.
- [ ] Provide links to a specific run and its pending interaction. Preserve
  that selection across reloads so opening the app returns to the intended
  stage instead of the default workflow editor.

## Workflow handoffs

- [ ] Create and save new workflows through Relay without manually adding a
  bootstrap YAML file. Keep prompts and agent execution bound to the selected
  project and stop downstream stages automatically when that binding is wrong.
- [ ] Handle generated planning and review documents without requiring manual
  Git exclusions before launch. Preserve existing documents and keep them
  unstaged and uncommitted unless the owner explicitly requests otherwise.
- [ ] Warn when required report handoffs use only `exists` outputs. Relay
  already retains files declared with `label`, `json_path`, or `yaml_path`.
  Guide workflow authors to those selectors and automatic verdict checks,
  while preserving actual human review and approval gates.
- [ ] Accept owner feedback while an agent is paused and resume it through
  Relay, without manually editing prompt files or restarting a worker.
- [ ] Clean up run-owned temporary files, browser profiles, and processes
  through Relay after the run finishes. Preserve personal browser sessions,
  credentials, unrelated files, and the owner's existing Relay data.
