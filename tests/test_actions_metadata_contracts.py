"""Local action metadata is validated before source freezing or Node execution."""

from io import StringIO
from typing import Any

import pytest
from ruamel.yaml import YAML

from relay.errors import WorkflowValidationError
from relay.workflows.actions.metadata import load_action, validate_action_inputs

BASE: dict[str, Any] = {
    "name": "Local",
    "description": "Metadata",
    "runs": {"using": "node20", "main": "main.js"},
}


@pytest.mark.parametrize(
    "change",
    [
        {"name": ""},
        {"unknown": True},
        {"inputs": {"bad.id": {"description": "Bad"}}},
        {"inputs": {"value": {"description": "Value", "unknown": True}}},
        {"inputs": {"value": {"description": "Value", "required": "true"}}},
        {"inputs": {"value": {"description": "Value", "default": 1}}},
        {"inputs": {"value": {"required": False}}},
        {"branding": {"unsupported": "value"}},
        {"branding": {"icon": 1}},
        {"runs": {"using": "composite", "unknown": True, "steps": []}},
        {"runs": {"using": "composite", "steps": []}},
        {"runs": {"using": "composite", "steps": [{"run": "echo"}]}},
        {
            "runs": {"using": "composite", "steps": [{"run": "echo", "shell": "bash"}]},
            "outputs": {"value": {"description": "Value"}},
        },
        {"runs": {"using": "node20", "main": "main.js", "pre": "pre.js"}},
        {"runs": {"using": "node20"}},
        {"runs": {"using": "node24", "main": "${{ inputs.script }}"}},
        {"runs": {"using": "docker", "image": "alpine"}},
    ],
)
def test_invalid_metadata_rejects_unsupported_or_incomplete_contracts(
    change: dict[str, Any],
) -> None:
    stream = StringIO()
    YAML().dump({**BASE, **change}, stream)
    with pytest.raises(WorkflowValidationError):
        load_action(stream.getvalue())


def test_metadata_size_syntax_and_declared_input_contracts() -> None:
    for text in ("#" * 1048577, "runs: ["):
        with pytest.raises(WorkflowValidationError):
            load_action(text)
    action = load_action(
        "name: Local\ndescription: Metadata\n"
        "inputs: {value: {description: Value, required: true, default: fallback}}\n"
        "runs: {using: node24, main: main.js, post: post.js, post-if: always()}\n"
    )
    validate_action_inputs(action, {})
    validate_action_inputs(action, {"value": "chosen"})
    with pytest.raises(WorkflowValidationError, match="unknown"):
        validate_action_inputs(action, {"other": "value"})
