"""Move steps on deprecated or removed built-in versions to the current version.

The update is pure: it reads only the text it is given and never executes,
fetches, or writes anything. The editor applies the result as an unsaved draft.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from relay.errors import WorkflowValidationError
from relay.workflows.importer import _dump, _jobs, _remove, _same_style, _steps

from .builtins import newer_versions
from .language import _read_document, workflow_diagnostics


@dataclass(frozen=True, slots=True)
class UpgradeResult:
    yaml: str
    changes: tuple[str, ...]
    unresolved: tuple[str, ...]


def _converted(reference: str, inputs: object) -> tuple[str, dict[str, object], list[str]]:
    """Apply each newer version's conversion in turn; return the reference and inputs."""
    if not isinstance(inputs, Mapping):
        message = "Expected a mapping."
        raise WorkflowValidationError(message)
    converted = {str(key): value for key, value in inputs.items()}
    notes: list[str] = []
    for action in newer_versions(reference):
        if action.upgrade is None:
            message = f"Relay cannot convert the inputs of {reference} to {action.reference}."
            raise WorkflowValidationError(message)
        converted, said = action.upgrade(converted)
        notes.extend(said)
        reference = action.reference
    return reference, converted, notes


def _replace_inputs(step: CommentedMap, inputs: Mapping[str, object]) -> None:
    """Write the converted inputs, keeping unchanged values and their comments."""
    current = step.get("with")
    if not isinstance(current, CommentedMap):
        if inputs:
            step["with"] = CommentedMap(inputs)
        return
    for key in [str(key) for key in current]:
        if key not in inputs:
            _remove(current, key)
    for key, value in inputs.items():
        if key not in current:
            current[key] = value
        elif current[key] != value:
            current[key] = _same_style(current[key], value) if isinstance(value, str) else value


def upgrade_builtins(text: str, *, source: Path | None = None) -> UpgradeResult:
    """Move deprecated built-in steps to the current version.

    Pure: it never reads other files, fetches, or writes. Each newer version's
    upgrade converts the inputs in turn, and each updated step adds a change
    such as ``Updated step 1 in job test from <old> to <new>.``. A step that
    cannot be converted stays as written and is listed in unresolved, with
    every diagnostic the result still has. A source with nothing to update
    comes back byte-identical.
    """
    # The validator's reader enforces the size, node, alias, and tag limits.
    _read_document(text)
    parser = YAML(typ="rt")
    parser.preserve_quotes = True
    document = parser.load(text)
    changes: list[str] = []
    unresolved: list[str] = []
    for job_id, job in _jobs(document):
        for index, step in _steps(job):
            old = step.get("uses")
            if not newer_versions(old):
                continue
            try:
                new, inputs, notes = _converted(str(old), step.get("with", {}))
            except WorkflowValidationError as error:
                unresolved.append(
                    f"Step {index + 1} in job {job_id}: {error.message} Update it by hand."
                )
                continue
            step["uses"] = _same_style(old, new)
            _replace_inputs(step, inputs)
            changes.append(f"Updated step {index + 1} in job {job_id} from {old} to {new}.")
            changes.extend(notes)
    upgraded = _dump(document, parser) if changes else text
    unresolved.extend(issue.message for issue in workflow_diagnostics(upgraded, source=source))
    return UpgradeResult(upgraded, tuple(changes), tuple(unresolved))


__all__ = ["UpgradeResult", "upgrade_builtins"]
