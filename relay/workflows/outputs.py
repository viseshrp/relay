"""Deterministic extraction of declared node outputs from worktree artifacts."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path

from ruamel.yaml import YAML

from relay.errors import OutputValidationError, PathSafetyError
from relay.paths import safe_resolve

from .schema import (
    DataPathSelectorValue,
    ExistsSelector,
    JsonPathSelector,
    LabelSelector,
    OutputSelector,
    YamlPathSelector,
)


def _artifact(worktree: Path, reference: str, *, require_file: bool = True) -> Path:
    try:
        path = safe_resolve(worktree, reference)
    except PathSafetyError:
        message = f"Output artifact {reference!r} escapes the node worktree."
        raise OutputValidationError(message) from None
    if require_file and not path.is_file():
        message = f"Output artifact {reference!r} does not exist."
        raise OutputValidationError(message)
    return path


def _read_text(path: Path, reference: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        message = f"Output artifact {reference!r} could not be read as UTF-8."
        raise OutputValidationError(message) from None


def _mapping_path(document: object, selector: DataPathSelectorValue) -> object:
    value = document
    keys = selector.path.split(".")
    if any(not key for key in keys):
        message = "Output key paths must contain non-empty dotted keys."
        raise OutputValidationError(message)
    for key in keys:
        if not isinstance(value, Mapping) or key not in value:
            message = f"Output key path {selector.path!r} does not resolve in the artifact."
            raise OutputValidationError(message)
        value = value[key]
    return value


def _label(worktree: Path, selector: LabelSelector) -> str:
    reference = selector.label.artifact
    text = _read_text(_artifact(worktree, reference), reference)
    prefix = f"{selector.label.label}: "
    for line in text.splitlines():
        if line.startswith(prefix):
            return line[len(prefix) :]
    message = f"Artifact {reference!r} has no exact {prefix!r} line."
    raise OutputValidationError(message)


def _json_path(worktree: Path, selector: JsonPathSelector) -> object:
    details = selector.json_path
    text = _read_text(_artifact(worktree, details.artifact), details.artifact)
    try:
        document = json.loads(text)
    except (json.JSONDecodeError, RecursionError):
        message = f"Output artifact {details.artifact!r} is not valid JSON."
        raise OutputValidationError(message) from None
    return _mapping_path(document, details)


def _yaml_path(worktree: Path, selector: YamlPathSelector) -> object:
    details = selector.yaml_path
    text = _read_text(_artifact(worktree, details.artifact), details.artifact)
    try:
        document = YAML(typ="safe").load(text)
    except Exception:
        message = f"Output artifact {details.artifact!r} is not valid YAML."
        raise OutputValidationError(message) from None
    return _mapping_path(document, details)


def extract_output(worktree: Path, selector: OutputSelector) -> object:
    """Apply exactly one selector without arbitrary code execution."""
    if isinstance(selector, ExistsSelector):
        return _artifact(worktree, selector.exists, require_file=False).exists()
    if isinstance(selector, LabelSelector):
        return _label(worktree, selector)
    if isinstance(selector, JsonPathSelector):
        return _json_path(worktree, selector)
    if isinstance(selector, YamlPathSelector):
        return _yaml_path(worktree, selector)
    message = "The output selector is not supported."
    raise OutputValidationError(message)


def extract_outputs(worktree: Path, selectors: Mapping[str, OutputSelector]) -> dict[str, object]:
    """Extract named outputs in declaration order, failing on the first invalid value."""
    return {name: extract_output(worktree, selector) for name, selector in selectors.items()}


__all__ = ["extract_output", "extract_outputs"]
