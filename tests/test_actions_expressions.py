"""Actions expression conformance using unmodified upstream fixtures."""

import json
from pathlib import Path

import pytest

from relay.errors import WorkflowValidationError
from relay.workflows.actions.expressions import condition, evaluate, interpolate, parse


def cases():
    root = Path(__file__).parent / "fixtures" / "actions" / "expressions"
    for path in sorted(root.glob("*.json")):
        for group, rows in json.loads(path.read_text()).items():
            for index, row in enumerate(rows):
                yield pytest.param(row, id=f"{path.stem}:{group}:{index}")


@pytest.mark.parametrize("row", list(cases()))
def test_official_expression_conformance(row):
    values = row.get("contexts", {})
    if "err" in row:
        with pytest.raises(WorkflowValidationError):
            evaluate(row["expr"], values)
        return
    actual = evaluate(row["expr"], values)
    assert actual == row["result"]["value"]
    kind = row["result"]["kind"]
    if kind == "Boolean":
        assert isinstance(actual, bool)
    if kind == "Number":
        assert isinstance(actual, (int, float)) and not isinstance(actual, bool)


def test_templates_and_status_checks():
    values = {"inputs": {"enabled": False, "title": "a"}, "_statuses": ["failure"]}
    assert interpolate("${{ inputs.enabled }}", values) is False
    assert interpolate("x ${{ format('{0}}}', inputs.title) }}", values) == "x a}"
    assert not condition("inputs.title == 'A'", values)
    assert condition("failure() && inputs.title == 'A'", values)
    assert condition("always()", values)


def test_expression_limits_and_names():
    with pytest.raises(WorkflowValidationError):
        parse("'" + "a" * 21_000 + "'")
    with pytest.raises(WorkflowValidationError):
        parse("(" * 51 + "true" + ")" * 51)
    with pytest.raises(WorkflowValidationError):
        parse("secrets.a", contexts=("inputs",))
    with pytest.raises(WorkflowValidationError):
        parse("__import__('os')")
