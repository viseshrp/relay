"""Public input contracts for Relay's versioned local action adapters."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from relay.errors import WorkflowValidationError

CONTRACTS: dict[str, tuple[set[str], set[str]]] = {
    "relay/agent@v1": (
        {
            "agent",
            "agents",
            "model",
            "effort",
            "prompt-files",
            "prompt",
            "report",
            "selector",
            "format",
            "field",
            "label",
            "auto-retry",
        },
        set(),
    ),
    "relay/command@v1": ({"argv", "command"}, set()),
    "relay/human-wait@v1": ({"prompt", "timeout-minutes"}, {"prompt"}),
    "relay/loop@v1": (
        {"workflow", "inputs", "max-iterations", "until-output", "equals"},
        {"workflow", "max-iterations"},
    ),
    "relay/validate-report@v1": ({"path", "report", "selector", "format", "field", "label"}, set()),
    "relay/validate-input@v1": ({"value", "type", "constraints"}, {"value", "type"}),
    "relay/upload-artifact@v1": ({"name", "path", "retention-days"}, {"path"}),
    "relay/download-artifact@v1": ({"name", "path", "run-id"}, {"name"}),
    "relay/cache@v1": ({"key", "path", "restore-keys"}, {"key", "path"}),
    "relay/restore-cache@v1": ({"key", "path", "restore-keys"}, {"key", "path"}),
    "relay/save-cache@v1": ({"key", "path"}, {"key", "path"}),
}


def validate_inputs(reference: str, inputs: Mapping[str, Any]) -> None:
    allowed, required = CONTRACTS[reference]
    if inputs.keys() - allowed or required - inputs.keys():
        message = f"{reference} has missing required or unknown action inputs."
        raise WorkflowValidationError(message)
    if reference == "relay/command@v1" and len({"argv", "command"} & inputs.keys()) != 1:
        message = "relay/command@v1 requires exactly one of argv or command."
        raise WorkflowValidationError(message)
    if reference == "relay/validate-report@v1" and not (
        {"path", "report", "selector"} & inputs.keys()
    ):
        message = "relay/validate-report@v1 requires path, report, or selector."
        raise WorkflowValidationError(message)
    if "permissions" in inputs:
        message = "Workflow permissions are not part of Relay's Actions dialect."
        raise WorkflowValidationError(message)
    if reference == "relay/loop@v1":
        maximum = inputs["max-iterations"]
        if isinstance(maximum, bool) or str(maximum) not in {str(i) for i in range(1, 101)}:
            message = "Loop max-iterations must be a literal integer between 1 and 100."
            raise WorkflowValidationError(message)
    format_name = inputs.get("format")
    if (
        format_name is not None
        and "${{" not in str(format_name)
        and format_name not in {"exists", "label", "json", "yaml"}
    ):
        message = "Report format must be exists, label, json, or yaml."
        raise WorkflowValidationError(message)
