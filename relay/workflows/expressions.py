"""A small expression interpreter over Relay's declared read-only context."""

from __future__ import annotations

import ast
from collections.abc import Mapping

from relay.errors import WorkflowValidationError

ExpressionValue = object
ExpressionContext = Mapping[str, object]

_ROOT_NAMES = frozenset({"inputs", "needs", "run", "loop"})
_COMPARE_NODES = (
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.In,
    ast.NotIn,
)


def _body(expression: str) -> str:
    stripped = expression.strip()
    if not stripped.startswith("${{") or not stripped.endswith("}}"):
        message = "Expressions must use the exact `${{ ... }}` wrapper."
        raise WorkflowValidationError(message)
    body = stripped[3:-2].strip()
    if not body:
        message = "An expression body must not be empty."
        raise WorkflowValidationError(message)
    return body


def _parse(expression: str) -> ast.Expression:
    try:
        parsed = ast.parse(_body(expression), mode="eval")
    except (SyntaxError, ValueError):
        message = "The expression contains invalid syntax."
        raise WorkflowValidationError(message) from None
    if not isinstance(parsed, ast.Expression):
        message = "The expression must contain one value."
        raise WorkflowValidationError(message)
    _validate_node(parsed.body)
    return parsed


def _validate_key(value: object) -> None:
    if isinstance(value, str) and value.startswith("__"):
        message = "Dunder keys are not allowed in expressions."
        raise WorkflowValidationError(message)


def _validate_node(node: ast.AST) -> None:
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, (str, int, float, bool, type(None))):
            message = f"Expression literal {type(node.value).__name__!r} is not allowed."
            raise WorkflowValidationError(message)
        _validate_key(node.value)
        return
    if isinstance(node, ast.Name):
        if node.id not in _ROOT_NAMES:
            message = f"Expression name {node.id!r} is not available."
            raise WorkflowValidationError(message)
        return
    if isinstance(node, ast.Attribute):
        _validate_key(node.attr)
        _validate_node(node.value)
        return
    if isinstance(node, ast.Subscript):
        _validate_node(node.value)
        _validate_node(node.slice)
        return
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        for item in node.elts:
            _validate_node(item)
        return
    if isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values, strict=True):
            if key is None:
                message = "Dictionary unpacking is not allowed."
                raise WorkflowValidationError(message)
            _validate_node(key)
            _validate_node(value)
        return
    if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
        for value in node.values:
            _validate_node(value)
        return
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.Not, ast.UAdd, ast.USub)):
        _validate_node(node.operand)
        return
    if isinstance(node, ast.Compare) and all(isinstance(item, _COMPARE_NODES) for item in node.ops):
        _validate_node(node.left)
        for comparator in node.comparators:
            _validate_node(comparator)
        return
    message = f"Expression construct {type(node).__name__!r} is not allowed."
    raise WorkflowValidationError(message)


def validate_expression(expression: str) -> None:
    """Reject syntax outside the documented whitelist without evaluating it."""
    _parse(expression)


def _mapping_value(container: object, key: object) -> object:
    _validate_key(key)
    if not isinstance(container, Mapping):
        message = "Expression access is allowed only on context mappings."
        raise WorkflowValidationError(message)
    try:
        return container[key]
    except (KeyError, TypeError):
        message = f"Expression context has no key {key!r}."
        raise WorkflowValidationError(message) from None


def _ordered_compare(left: object, operation: ast.cmpop, right: object) -> bool:
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        if isinstance(left, bool) or isinstance(right, bool):
            message = "Boolean values support equality comparisons only."
            raise WorkflowValidationError(message)
        if isinstance(operation, ast.Lt):
            return left < right
        if isinstance(operation, ast.LtE):
            return left <= right
        if isinstance(operation, ast.Gt):
            return left > right
        return left >= right
    if isinstance(left, str) and isinstance(right, str):
        if isinstance(operation, ast.Lt):
            return left < right
        if isinstance(operation, ast.LtE):
            return left <= right
        if isinstance(operation, ast.Gt):
            return left > right
        return left >= right
    message = "Ordered comparisons require two numbers or two strings."
    raise WorkflowValidationError(message)


def _contains(container: object, value: object) -> bool:
    try:
        if isinstance(container, Mapping):
            return value in container
        if isinstance(container, str):
            if not isinstance(value, str):
                message = "String membership requires a string value."
                raise WorkflowValidationError(message)
            return value in container
        if isinstance(container, (list, tuple, set, frozenset)):
            return value in container
    except TypeError:
        message = "Expression membership values are incompatible."
        raise WorkflowValidationError(message) from None
    message = "The right side of a membership test must be a collection."
    raise WorkflowValidationError(message)


def _compare(left: object, operation: ast.cmpop, right: object) -> bool:
    if isinstance(operation, ast.Eq):
        return left == right
    if isinstance(operation, ast.NotEq):
        return left != right
    if isinstance(operation, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
        return _ordered_compare(left, operation, right)
    if isinstance(operation, ast.In):
        return _contains(right, left)
    if isinstance(operation, ast.NotIn):
        return not _contains(right, left)
    message = "Expression comparison operator is not allowed."
    raise WorkflowValidationError(message)


def _evaluate(node: ast.AST, context: ExpressionContext) -> object:
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        return _mapping_value(context, node.id)
    if isinstance(node, ast.Attribute):
        return _mapping_value(_evaluate(node.value, context), node.attr)
    if isinstance(node, ast.Subscript):
        return _mapping_value(_evaluate(node.value, context), _evaluate(node.slice, context))
    if isinstance(node, ast.List):
        return [_evaluate(item, context) for item in node.elts]
    if isinstance(node, ast.Tuple):
        return tuple(_evaluate(item, context) for item in node.elts)
    if isinstance(node, ast.Set):
        try:
            return {_evaluate(item, context) for item in node.elts}
        except TypeError:
            message = "Expression set members must be hashable."
            raise WorkflowValidationError(message) from None
    if isinstance(node, ast.Dict):
        result: dict[object, object] = {}
        try:
            for key, value in zip(node.keys, node.values, strict=True):
                if key is not None:
                    result[_evaluate(key, context)] = _evaluate(value, context)
        except TypeError:
            message = "Expression dictionary keys must be hashable."
            raise WorkflowValidationError(message) from None
        return result
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            result: object = True
            for value in node.values:
                result = _evaluate(value, context)
                if not result:
                    return result
            return result
        result = False
        for value in node.values:
            result = _evaluate(value, context)
            if result:
                return result
        return result
    if isinstance(node, ast.UnaryOp):
        operand = _evaluate(node.operand, context)
        if isinstance(node.op, ast.Not):
            return not operand
        if not isinstance(operand, (int, float)) or isinstance(operand, bool):
            message = "Unary numeric operators require a number."
            raise WorkflowValidationError(message)
        return +operand if isinstance(node.op, ast.UAdd) else -operand
    if isinstance(node, ast.Compare):
        left = _evaluate(node.left, context)
        for operation, comparator in zip(node.ops, node.comparators, strict=True):
            right = _evaluate(comparator, context)
            if not _compare(left, operation, right):
                return False
            left = right
        return True
    message = "The expression contains an unsupported value."
    raise WorkflowValidationError(message)


def evaluate_expression(expression: str, context: ExpressionContext) -> ExpressionValue:
    """Evaluate a validated expression without Python `eval` or object attributes."""
    return _evaluate(_parse(expression).body, context)


__all__ = ["ExpressionContext", "ExpressionValue", "evaluate_expression", "validate_expression"]
