# Relay TODO

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
