"""The `${{ ... }}` expression language: whitelist validation and evaluation."""

from __future__ import annotations

import pytest

from relay.errors import WorkflowValidationError
from relay.workflows.expressions import evaluate_expression, validate_expression

CONTEXT: dict[str, object] = {
    "inputs": {"mode": "review", "count": 3, "ratio": 0.5, "flag": True, "names": ["a", "b"]},
    "needs": {"build": {"outputs": {"ready": "Yes", "items": {"x": 1}}}},
    "run": {"id": "run-1"},
    "loop": {"index": 2},
}


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("${{ inputs.mode }}", "review"),
        ("${{ inputs['count'] }}", 3),
        ("${{ needs.build.outputs.ready == 'Yes' }}", True),
        ("${{ needs.build.outputs.ready != 'Yes' }}", False),
        ("${{ loop.index >= 2 }}", True),
        ("${{ loop.index > 2 }}", False),
        ("${{ loop.index < 3 }}", True),
        ("${{ loop.index <= 1 }}", False),
        ("${{ 'a' < 'b' }}", True),
        ("${{ 'a' <= 'a' }}", True),
        ("${{ 'b' > 'a' }}", True),
        ("${{ 'a' >= 'b' }}", False),
        ("${{ 1 < 2 < 3 }}", True),
        ("${{ 3 < 2 < 1 }}", False),
        ("${{ 'a' in inputs.names }}", True),
        ("${{ 'z' not in inputs.names }}", True),
        ("${{ 'x' in needs.build.outputs.items }}", True),
        ("${{ 'rev' in inputs.mode }}", True),
        ("${{ inputs.flag and inputs.count }}", 3),
        ("${{ inputs.flag and 0 }}", 0),
        ("${{ 0 or inputs.mode }}", "review"),
        ("${{ 0 or '' }}", ""),
        ("${{ not inputs.flag }}", False),
        ("${{ -inputs.count }}", -3),
        ("${{ +inputs.ratio }}", 0.5),
        ("${{ [1, 2] }}", [1, 2]),
        ("${{ (1, 'a') }}", (1, "a")),
        ("${{ {1, 2} }}", {1, 2}),
        ("${{ {'k': inputs.count} }}", {"k": 3}),
        ("${{ 'k' in {'k': 1} }}", True),
        ("${{ None }}", None),
    ],
)
def test_a_supported_expression_evaluates_to_its_value(expression: str, expected: object) -> None:
    assert evaluate_expression(expression, CONTEXT) == expected


@pytest.mark.parametrize(
    "expression",
    [
        "inputs.mode",
        "${{   }}",
        "${{ inputs. }}",
        "${{ __import__('os') }}",
        "${{ inputs['__dict__'] }}",
        "${{ open('x') }}",
        "${{ os.path }}",
        "${{ inputs.__class__ }}",
        "${{ [x for x in inputs] }}",
        "${{ {**inputs} }}",
        "${{ inputs.count + 1 }}",
        "${{ ~inputs.count }}",
        "${{ inputs is None }}",
        "${{ b'bytes' }}",
        "${{ lambda: 1 }}",
    ],
)
def test_a_construct_outside_the_allow_list_is_rejected(expression: str) -> None:
    with pytest.raises(WorkflowValidationError):
        validate_expression(expression)


@pytest.mark.parametrize(
    "expression",
    [
        "${{ inputs.missing }}",
        "${{ inputs.mode.length }}",
        "${{ inputs.flag > 1 }}",
        "${{ inputs.mode > 1 }}",
        "${{ 1 in inputs.mode }}",
        "${{ 1 in inputs.count }}",
        "${{ [1] in {'a': 1} }}",
        "${{ {[1]} }}",
        "${{ {[1]: 2} }}",
        "${{ -inputs.mode }}",
        "${{ -inputs.flag }}",
        "${{ inputs[['k']] }}",
    ],
)
def test_a_runtime_type_error_is_a_validation_error(expression: str) -> None:
    with pytest.raises(WorkflowValidationError):
        evaluate_expression(expression, CONTEXT)
