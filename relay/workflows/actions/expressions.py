"""Bounded Actions expressions, independent of Python evaluation and processes.

Conformance fixtures are pinned in tests/fixtures/actions. The old Python
expression interpreter remains exclusively for historical Relay snapshots.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from contextvars import ContextVar
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
import re
from typing import Any, TypeAlias, cast

from relay.errors import WorkflowValidationError

MAX_LENGTH = 21_000
MAX_DEPTH = 50
MAX_RESULT = 1_048_576
CONTEXTS = frozenset(
    {
        "github",
        "env",
        "vars",
        "job",
        "jobs",
        "steps",
        "runner",
        "secrets",
        "strategy",
        "matrix",
        "needs",
        "inputs",
    }
)
FUNCTIONS = {
    "contains": (2, 2),
    "startswith": (2, 2),
    "endswith": (2, 2),
    "format": (1, 255),
    "join": (1, 2),
    "tojson": (1, 1),
    "fromjson": (1, 1),
    "case": (3, 255),
    "hashfiles": (1, 255),
    "always": (0, 0),
    "success": (0, 255),
    "failure": (0, 255),
    "cancelled": (0, 0),
}
STATUS_FUNCTIONS = frozenset({"always", "success", "failure", "cancelled"})
Tree: TypeAlias = tuple[Any, ...]
_ABSENT = object()
_BUDGET: ContextVar[list[int] | None] = ContextVar("actions_expression_budget", default=None)


def _error(message: str, position: int | None = None) -> WorkflowValidationError:
    context = {"column": position + 1} if position is not None else {}
    return WorkflowValidationError(message, context=context)


def upper(value: str) -> str:
    """Actions' ordinal-ignore-case comparison preserves dotless i."""
    return "\u0131".join(part.upper() for part in value.split("\u0131"))


def number(value: object) -> float:
    if value is None:
        return 0.0
    if isinstance(value, bool):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    if not isinstance(value, str):
        return math.nan
    value = value.strip()
    if not value:
        return 0.0
    if re.fullmatch(r"0[xX][0-9a-fA-F]+|0[oO][0-7]+|0[bB][01]+", value):
        return float(int(value, 0))
    if value in {"Infinity", "+Infinity", "-Infinity"}:
        return float(value.replace("Infinity", "inf"))
    if re.fullmatch(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?", value):
        return float(value)
    return math.nan


def string(value: object) -> str:
    """Actions string conversion, including empty object/array conversions."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        return value
    if isinstance(value, (int, float)):
        numeric = float(value)
        if math.isnan(numeric):
            return "NaN"
        if math.isinf(numeric):
            return "Infinity" if numeric > 0 else "-Infinity"
        if numeric == 0:
            return "0"
        if numeric.is_integer() and abs(numeric) < 1e21:
            return str(int(numeric))
        rendered = format(numeric, ".15g")
        if 1e-6 <= abs(numeric) < 1e21 and "e" in rendered:
            rendered = format(numeric, ".15f").rstrip("0").rstrip(".")
        return re.sub(r"e([+-])0+", r"e\1", rendered)
    return "Array" if isinstance(value, list) else "Object"


def truthy(value: object) -> bool:
    if value is None or value is False or value == "":
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return value != 0 and not math.isnan(float(value))
    return True


def _kind(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    if isinstance(value, str):
        return "string"
    return "array" if isinstance(value, list) else "object"


def _coerce(left: object, right: object) -> tuple[object, object]:
    if _kind(left) == _kind(right):
        return left, right
    if _kind(left) in {"null", "boolean"}:
        return _coerce(number(left), right)
    if _kind(right) in {"null", "boolean"}:
        return _coerce(left, number(right))
    if {_kind(left), _kind(right)} == {"number", "string"}:
        return number(left), number(right)
    return left, right


def equal(left: object, right: object) -> bool:
    left, right = _coerce(left, right)
    if _kind(left) != _kind(right):
        return False
    if isinstance(left, str) and isinstance(right, str):
        return upper(left) == upper(right)
    if isinstance(left, (list, Mapping)):
        return left is right
    return left == right


@dataclass(frozen=True, slots=True)
class Token:
    kind: str
    value: object
    position: int


def _lex(source: str) -> list[Token]:
    if len(source) > MAX_LENGTH:
        message = f"Expression exceeds {MAX_LENGTH} characters."
        raise _error(message)
    result = []
    offset = 0
    while offset < len(source):
        start = offset
        char = source[offset]
        if char.isspace():
            offset += 1
            continue
        if char == "'":
            offset += 1
            content = []
            while offset < len(source):
                if source[offset] == "'":
                    if offset + 1 < len(source) and source[offset + 1] == "'":
                        content.append("'")
                        offset += 2
                        continue
                    offset += 1
                    break
                content.append(source[offset])
                offset += 1
            else:
                message = "Unterminated expression string."
                raise _error(message, start)
            result.append(Token("literal", "".join(content), start))
            continue
        pair = source[offset : offset + 2]
        if pair in {"&&", "||", "==", "!=", "<=", ">="}:
            result.append(Token(pair, pair, start))
            offset += 2
            continue
        numeric = (
            char.isdigit()
            or char in {"+", "-"}
            or (char == "." and (not result or result[-1].kind not in {"name", "]", ")", "*"}))
        )
        if numeric:
            offset += 1
            while offset < len(source) and not re.match(r"[\s()\[\],!><=&|]", source[offset]):
                offset += 1
            value = number(source[start:offset])
            if math.isnan(value):
                message = "Invalid expression number."
                raise _error(message, start)
            result.append(Token("literal", value, start))
            continue
        if char in "()[],.!<>*":
            result.append(Token(char, char, start))
            offset += 1
            continue
        match = re.match(r"[a-zA-Z_][a-zA-Z_0-9-]*", source[offset:])
        if match is None:
            message = "Unexpected expression symbol."
            raise _error(message, start)
        identifier = match.group()
        offset += len(identifier)
        literals = {
            "true": True,
            "false": False,
            "null": None,
            "NaN": math.nan,
            "Infinity": math.inf,
        }
        is_literal = identifier in literals and (not result or result[-1].kind != ".")
        result.append(
            Token(
                "literal" if is_literal else "name",
                literals[identifier] if is_literal else identifier,
                start,
            )
        )
    result.append(Token("end", None, len(source)))
    return result


class Parser:
    tokens: list[Token]
    index: int
    contexts: frozenset[str]
    functions: frozenset[str]

    def __init__(self, source: str, contexts: Sequence[str], functions: Sequence[str]) -> None:
        self.tokens = _lex(source)
        self.index = 0
        self.contexts = frozenset(name.lower() for name in contexts)
        self.functions = frozenset(name.lower() for name in functions)

    def take(self, kind: str) -> Token:
        token = self.tokens[self.index]
        if token.kind != kind:
            message = f"Expected {kind!r} in expression."
            raise _error(message, token.position)
        self.index += 1
        return token

    def parse(self) -> Tree:
        if self.tokens[0].kind == "end":
            return ("literal", None)
        tree = self.expression(0, 0)
        self.take("end")

        def tree_depth(item: Tree) -> int:
            if not item:
                return 0
            children = item[2] if item[0] == "call" else item[1:]
            if item[0] in {"&&", "||"}:
                flattened = []
                pending = list(children)
                while pending:
                    child = pending.pop()
                    if isinstance(child, tuple) and child and child[0] == item[0]:
                        pending.extend(child[1:])
                    else:
                        flattened.append(child)
                children = flattened
            return 1 + max(
                (tree_depth(child) for child in children if isinstance(child, tuple)), default=0
            )

        if tree_depth(tree) > MAX_DEPTH:
            message = f"Expression exceeds depth {MAX_DEPTH}."
            raise _error(message)
        return tree

    def expression(self, precedence: int, depth: int) -> Tree:
        if depth > MAX_DEPTH:
            message = f"Expression exceeds depth {MAX_DEPTH}."
            raise _error(message)
        token = self.tokens[self.index]
        if token.kind == "!":
            self.index += 1
            left = ("not", self.expression(6, depth + 1))
        elif token.kind == "(":
            self.index += 1
            left = self.expression(0, depth + 1)
            self.take(")")
        elif token.kind == "literal":
            self.index += 1
            left = ("literal", token.value)
        elif token.kind == "name":
            self.index += 1
            name = str(token.value).lower()
            if self.tokens[self.index].kind == "(":
                if name not in self.functions or name not in FUNCTIONS:
                    message = f"Unrecognized function: {name}."
                    raise _error(message, token.position)
                self.index += 1
                arguments = []
                if self.tokens[self.index].kind != ")":
                    while True:
                        arguments.append(self.expression(0, depth + 1))
                        if self.tokens[self.index].kind != ",":
                            break
                        self.index += 1
                self.take(")")
                minimum, maximum = FUNCTIONS[name]
                if not minimum <= len(arguments) <= maximum:
                    message = f"Invalid number of arguments to {name}."
                    raise _error(message, token.position)
                if name == "case" and len(arguments) % 2 == 0:
                    message = "case requires an odd number of arguments."
                    raise _error(message, token.position)
                left = ("call", name, tuple(arguments))
            else:
                if name not in self.contexts:
                    message = f"Unrecognized named-value: {name}."
                    raise _error(message, token.position)
                left = ("context", name)
        else:
            message = "Unexpected expression symbol."
            raise _error(message, token.position)

        while self.tokens[self.index].kind in {".", "["}:
            kind = self.tokens[self.index].kind
            self.index += 1
            if self.tokens[self.index].kind == "*":
                self.index += 1
                key = ("star",)
            elif kind == ".":
                key = ("literal", self.take("name").value)
            else:
                key = self.expression(0, depth + 1)
            if kind == "[":
                self.take("]")
            left = ("index", left, key)
        levels = {"||": 1, "&&": 2, "==": 3, "!=": 3, "<": 4, "<=": 4, ">": 4, ">=": 4}
        while levels.get(self.tokens[self.index].kind, 0) > precedence:
            operator = self.tokens[self.index].kind
            self.index += 1
            right = self.expression(levels[operator], depth + 1)
            left = (operator, left, right)
        return left


def parse(
    source: str,
    *,
    contexts: Sequence[str] = tuple(CONTEXTS),
    functions: Sequence[str] = tuple(FUNCTIONS),
) -> Tree:
    """Check all branches and return a bounded tree, without executing anything."""
    return Parser(source, contexts, functions).parse()


class Filtered(list[object]):
    """Distinguish an object filter from an ordinary array during projection."""


def _lookup(value: object, key: object) -> object:
    if isinstance(key, (list, Mapping)):
        return _ABSENT
    if isinstance(value, Mapping):
        name = upper(string(key))
        return next((item for k, item in value.items() if upper(str(k)) == name), _ABSENT)
    if isinstance(value, list):
        index = number(key)
        if math.isfinite(index) and index >= 0 and float(index).is_integer() and index < len(value):
            return value[int(index)]
    return _ABSENT


def _jsonable(value: object) -> object:
    if isinstance(value, float):
        if not math.isfinite(value):
            return None
        return int(value) if float(value).is_integer() else value
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    if isinstance(value, Mapping):
        # JavaScript enumerates integer keys first, in numeric order.
        keys = sorted(
            value,
            key=lambda k: (
                (0, int(str(k)))
                if re.fullmatch(r"0|[1-9][0-9]*", str(k))
                else (1, list(value).index(k))
            ),
        )
        return {str(key): _jsonable(value[key]) for key in keys}
    return value


def _format(arguments: list[object]) -> str:
    source = string(arguments[0])
    output = []
    offset = 0
    while offset < len(source):
        if source[offset : offset + 2] in {"{{", "}}"}:
            output.append(source[offset])
            offset += 2
        elif source[offset] == "{":
            match = re.match(r"\{([0-9]+)[^}]*\}", source[offset:])
            if match is None or int(match[1]) + 1 >= len(arguments):
                message = "Invalid format string or missing argument."
                raise _error(message)
            output.append(string(arguments[int(match[1]) + 1]))
            offset += len(match[0])
        elif source[offset] == "}":
            message = "Invalid format string."
            raise _error(message)
        else:
            output.append(source[offset])
            offset += 1
    return "".join(output)


def _hash_files(workspace: Path | None, patterns: list[object]) -> str:
    if workspace is None:
        return ""
    from .patterns import select_paths

    selected = select_paths(workspace, [string(item) for item in patterns], files_only=True)
    digest = sha256()
    for path in selected:
        file_digest = sha256()
        with path.open("rb") as stream:
            while chunk := stream.read(65_536):
                file_digest.update(chunk)
        digest.update(file_digest.digest())
    return digest.hexdigest() if selected else ""


def _reject_json_constant(_constant: str) -> None:
    raise ValueError


def _call(
    name: str, args: list[object], values: Mapping[str, object], workspace: Path | None
) -> object:
    if name in STATUS_FUNCTIONS:
        if name == "always":
            return True
        if name == "cancelled":
            return values.get("_cancelled", False) is True
        statuses = values.get("_statuses", [])
        if not isinstance(statuses, list):
            statuses = []
        if args:
            needs = values.get("needs", {})
            statuses = [_lookup(_lookup(needs, item), "result") for item in args]
        return (
            all(item == "success" for item in statuses)
            if name == "success"
            else any(item == "failure" for item in statuses)
        )
    if name == "hashfiles":
        return _hash_files(workspace, args)
    if name == "format":
        return _format(args)
    if name == "case":
        for index in range(0, len(args) - 1, 2):
            if not isinstance(args[index], bool):
                message = "case predicate must evaluate to a boolean value"
                raise _error(message)
            if args[index]:
                return args[index + 1]
        return args[-1]
    if name == "tojson":
        return json.dumps(_jsonable(args[0]), ensure_ascii=False, indent=2)
    if name == "fromjson":
        try:
            return json.loads(string(args[0]), parse_constant=_reject_json_constant)
        except (ValueError, RecursionError):
            message = "fromJSON requires valid JSON."
            raise _error(message) from None
    if name == "join":
        separator = (
            string(args[1]) if len(args) > 1 and not isinstance(args[1], (list, Mapping)) else ","
        )
        return (
            separator.join(string(item) for item in args[0])
            if isinstance(args[0], list)
            else ""
            if isinstance(args[0], Mapping)
            else string(args[0])
        )
    if name == "contains" and isinstance(args[0], list):
        return any(equal(item, args[1]) for item in args[0])
    if isinstance(args[0], (list, Mapping)) or isinstance(args[1], (list, Mapping)):
        return False
    left, right = upper(string(args[0])), upper(string(args[1]))
    if name == "contains":
        return right in left
    return left.startswith(right) if name == "startswith" else left.endswith(right)


def _evaluate(tree: Tree, values: Mapping[str, object], workspace: Path | None) -> object:
    result = _evaluate_inner(tree, values, workspace)
    size = len(json.dumps(_jsonable(result), ensure_ascii=False).encode("utf-16-le"))
    budget = _BUDGET.get()
    if budget is not None:
        budget[0] += size
    if size > MAX_RESULT or (budget is not None and budget[0] > MAX_RESULT):
        message = "Expression result exceeds the resource limit."
        raise _error(message)
    return result


def _evaluate_inner(tree: Tree, values: Mapping[str, object], workspace: Path | None) -> object:
    kind = tree[0]
    if kind == "literal":
        return tree[1]
    if kind == "context":
        found = _lookup(values, tree[1])
        return None if found is _ABSENT else found
    if kind == "not":
        return not truthy(_evaluate(tree[1], values, workspace))
    if kind == "call":
        return _call(
            str(tree[1]), [_evaluate(arg, values, workspace) for arg in tree[2]], values, workspace
        )
    left = _evaluate(tree[1], values, workspace)
    if kind == "index":
        star = tree[2][0] == "star"
        key = None if star else _evaluate(tree[2], values, workspace)
        if star:
            if isinstance(left, Filtered):
                return Filtered(
                    item
                    for group in left
                    for item in (
                        group.values()
                        if isinstance(group, Mapping)
                        else group
                        if isinstance(group, list)
                        else []
                    )
                )
            return Filtered(
                left.values()
                if isinstance(left, Mapping)
                else left
                if isinstance(left, list)
                else []
            )
        if isinstance(left, Filtered):
            return Filtered(found for item in left if (found := _lookup(item, key)) is not _ABSENT)
        found = _lookup(left, key)
        return None if found is _ABSENT else found
    if kind == "&&":
        return _evaluate(tree[2], values, workspace) if truthy(left) else left
    if kind == "||":
        return left if truthy(left) else _evaluate(tree[2], values, workspace)
    right = _evaluate(tree[2], values, workspace)
    if kind in {"==", "!="}:
        return equal(left, right) if kind == "==" else not equal(left, right)
    left, right = _coerce(left, right)
    if _kind(left) != _kind(right) or _kind(left) not in {"number", "boolean", "string"}:
        return False
    if isinstance(left, str) and isinstance(right, str):
        left, right = upper(left), upper(right)
    if kind == "<":
        return cast(Any, left) < right
    if kind == "<=":
        return cast(Any, left) <= right
    if kind == ">":
        return cast(Any, left) > right
    return cast(Any, left) >= right


def evaluate(
    source: str,
    values: Mapping[str, object],
    *,
    workspace: Path | None = None,
    contexts: Sequence[str] | None = None,
    functions: Sequence[str] = tuple(FUNCTIONS),
) -> object:
    names = tuple(values) if contexts is None else contexts
    token = _BUDGET.set([0])
    try:
        return _evaluate(parse(source, contexts=names, functions=functions), values, workspace)
    finally:
        _BUDGET.reset(token)


def segments(value: str) -> list[tuple[bool, str]]:
    """Split template expressions without mistaking quoted braces for delimiters."""
    result = []
    offset = 0
    while (start := value.find("${{", offset)) >= 0:
        if start > offset:
            result.append((False, value[offset:start]))
        index = start + 3
        quoted = False
        while index < len(value):
            if value[index] == "'":
                if quoted and index + 1 < len(value) and value[index + 1] == "'":
                    index += 2
                    continue
                quoted = not quoted
            if not quoted and value[index : index + 2] == "}}":
                result.append((True, value[start + 3 : index].strip()))
                offset = index + 2
                break
            index += 1
        else:
            message = "Expression is not closed."
            raise _error(message, start)
    if offset < len(value):
        result.append((False, value[offset:]))
    return result


def interpolate(
    value: object, values: Mapping[str, object], *, workspace: Path | None = None
) -> object:
    if isinstance(value, str):
        parts = segments(value)
        if len(parts) == 1 and parts[0][0]:
            return evaluate(parts[0][1], values, workspace=workspace)
        return "".join(
            string(evaluate(part, values, workspace=workspace)) if expr else part
            for expr, part in parts
        )
    if isinstance(value, list):
        return [interpolate(item, values, workspace=workspace) for item in value]
    if isinstance(value, Mapping):
        return {
            str(key): interpolate(item, values, workspace=workspace) for key, item in value.items()
        }
    return value


def condition(
    value: object, values: Mapping[str, object], *, workspace: Path | None = None
) -> bool:
    if value is None:
        return truthy(_call("success", [], values, workspace))
    if not isinstance(value, str):
        return truthy(value) and truthy(_call("success", [], values, workspace))
    parts = segments(value)
    source = parts[0][1] if len(parts) == 1 and parts[0][0] else value
    tree = parse(source, contexts=tuple(values))

    def uses_status(item: Tree) -> bool:
        if not item:
            return False
        return (item[0] == "call" and item[1] in STATUS_FUNCTIONS) or any(
            uses_status(child) for child in item[1:] if isinstance(child, tuple)
        )

    if not uses_status(tree) and not truthy(_call("success", [], values, workspace)):
        return False
    token = _BUDGET.set([0])
    try:
        return truthy(_evaluate(tree, values, workspace))
    finally:
        _BUDGET.reset(token)
