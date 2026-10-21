"""Convert a GitHub Actions workflow file into a Relay workflow draft.

The conversion is pure: it reads only the text it is given and never executes,
fetches, or writes anything. Each edit adds one sentence to ``changes``;
whatever still needs the owner's attention is listed in ``unresolved``.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from io import StringIO
import re
from typing import Any

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap, CommentedSeq
from ruamel.yaml.error import CommentMark
from ruamel.yaml.tokens import CommentToken

from .actions.builtins import builtin, current_builtin
from .actions.language import (
    EVENTS,
    FILE_VARIABLES,
    PLATFORM_NAMES,
    _read_document,
    workflow_diagnostics,
)

# GitHub action -> the Relay built-in that replaces it and the inputs that keep
# their meaning there. Every other input is dropped and reported.
_REPLACEMENTS: dict[str, tuple[str, tuple[str, ...]]] = {
    "actions/upload-artifact": ("upload-artifact", ("name", "path", "retention-days")),
    "actions/download-artifact": ("download-artifact", ("name", "path")),
    "actions/cache": ("cache", ("key", "path", "restore-keys")),
    "actions/cache/restore": ("restore-cache", ("key", "path", "restore-keys")),
    "actions/cache/save": ("save-cache", ("key", "path", "restore-keys")),
}
_REMOVED_FIELDS = ("permissions", "services", "container")
_REUSABLE = "./.github/workflows/"
_EXPRESSION = re.compile(r"\$\{\{(.*?)\}\}", re.DOTALL)
_QUOTED = re.compile(r"'(?:[^']|'')*'")
# github.event.inputs.<name> first, so it is not read as github.event.
_PLATFORM_NAME = re.compile(
    r"(?<![\w.-])(?:github\.event\.inputs\.([A-Za-z_][\w-]*)"
    r"|(github|runner)\.([A-Za-z_]\w*)(?![\w-]))"
)


@dataclass(frozen=True, slots=True)
class ImportResult:
    yaml: str
    changes: tuple[str, ...]
    unresolved: tuple[str, ...]


def convert_github_workflow(text: str) -> ImportResult:
    """Translate known fields; never execute or fetch anything.

    For example, a job's ``runs-on: ubuntu-latest`` is removed with the change
    ``Removed runs-on from job test; jobs run on this computer.``. Text that is
    not a YAML mapping raises the same WorkflowValidationError as validation.
    """
    # The validator's reader enforces the size, node, alias, and tag limits.
    _read_document(text)
    parser = YAML(typ="rt")
    parser.preserve_quotes = True
    document: CommentedMap = parser.load(text)
    changes: list[str] = []
    unresolved: list[str] = []
    jobs = _jobs(document)
    for job_id, job in jobs:
        if "runs-on" in job:
            _remove(job, "runs-on")
            changes.append(f"Removed runs-on from job {job_id}; jobs run on this computer.")
    for field in _REMOVED_FIELDS:
        if field in document:
            _remove(document, field)
            changes.append(f"Removed {field} from the workflow.")
    for job_id, job in jobs:
        for field in _REMOVED_FIELDS:
            if field in job:
                _remove(job, field)
                changes.append(f"Removed {field} from job {job_id}.")
    changes.extend(_remove_hosted_triggers(document))
    for job_id, job in jobs:
        for _ in _remove_steps(job, lambda base: base == "actions/checkout"):
            changes.append(
                f"Removed actions/checkout from job {job_id}; jobs already run in a working copy."
            )
    for job_id, job in jobs:
        for reference in _remove_steps(job, lambda base: base.startswith("actions/setup-")):
            changes.append(
                f"Removed {reference} from job {job_id}; use the tool installed on this computer."
            )
    for bases in (
        ("actions/upload-artifact",),
        ("actions/download-artifact",),
        ("actions/cache", "actions/cache/restore", "actions/cache/save"),
    ):
        for job_id, job in jobs:
            changes.extend(_replace_steps(job, job_id, bases))
    for job_id, job in jobs:
        reference = job.get("uses")
        if isinstance(reference, str) and reference.startswith(_REUSABLE):
            name = reference.removeprefix(_REUSABLE)
            job["uses"] = _same_style(reference, f"./.relay/workflows/{name}")
            changes.append(f"Pointed job {job_id} at ./.relay/workflows/{name}.")
            unresolved.append(f"Import .github/workflows/{name} too.")
    changes.extend(_rename_expressions(document))
    changes.extend(_rename_file_variables(jobs))
    for job_id, job in jobs:
        for index, step in _steps(job):
            reference = step.get("uses")
            if (
                isinstance(reference, str)
                and builtin(reference) is None
                and not reference.startswith("./.relay/actions/")
            ):
                unresolved.append(
                    f"Step {index + 1} in job {job_id} uses {reference}. "
                    "Replace it with a run step or a relay action."
                )
    converted = _dump(document, parser)
    unresolved.extend(issue.message for issue in workflow_diagnostics(converted))
    return ImportResult(converted, tuple(changes), tuple(unresolved))


def _jobs(document: CommentedMap) -> list[tuple[str, CommentedMap]]:
    jobs = document.get("jobs")
    if not isinstance(jobs, CommentedMap):
        return []
    return [(str(key), job) for key, job in jobs.items() if isinstance(job, CommentedMap)]


def _steps(job: CommentedMap) -> list[tuple[int, CommentedMap]]:
    """A job's step mappings with their positions."""
    steps = job.get("steps")
    if not isinstance(steps, CommentedSeq):
        return []
    return [(index, step) for index, step in enumerate(steps) if isinstance(step, CommentedMap)]


def _base(step: CommentedMap) -> str | None:
    """The action a step uses without its version, such as `actions/checkout`."""
    reference = step.get("uses")
    return reference.partition("@")[0].lower() if isinstance(reference, str) else None


def _remove_hosted_triggers(document: CommentedMap) -> list[str]:
    changes: list[str] = []
    triggers = document.get("on")
    if isinstance(triggers, CommentedMap):
        for event in [str(key) for key in triggers]:
            if event not in EVENTS:
                _remove(triggers, event)
                changes.append(f"Removed the {event} trigger; it has no local equivalent.")
        remaining = len(triggers)
    elif isinstance(triggers, CommentedSeq):
        hosted = [index for index, event in enumerate(triggers) if str(event) not in EVENTS]
        for index in hosted:
            changes.append(f"Removed the {triggers[index]} trigger; it has no local equivalent.")
        for index in reversed(hosted):
            _remove(triggers, index)
        remaining = len(triggers)
    elif isinstance(triggers, str) and triggers not in EVENTS:
        changes.append(f"Removed the {triggers} trigger; it has no local equivalent.")
        remaining = 0
    else:
        remaining = 0 if triggers is None else 1
    if not remaining:
        if "on" in document:
            document["on"] = "workflow_dispatch"
        else:
            position = list(document).index("name") + 1 if "name" in document else 0
            document.insert(position, "on", "workflow_dispatch")
        changes.append("Added workflow_dispatch so the workflow can be run by hand.")
    return changes


def _remove_steps(job: CommentedMap, matches: Callable[[str], bool]) -> list[str]:
    """Remove the steps whose action matches; return their references in order."""
    found = [(index, step) for index, step in _steps(job) if matches(_base(step) or "")]
    # Delete from the end so earlier positions stay valid.
    for index, _ in reversed(found):
        _remove(job["steps"], index)
    return [str(step["uses"]) for _, step in found]


def _replace_steps(job: CommentedMap, job_id: str, bases: tuple[str, ...]) -> list[str]:
    changes = []
    for _, step in _steps(job):
        base = _base(step)
        if base not in bases:
            continue
        name, kept = _REPLACEMENTS[base]
        action = current_builtin(name)
        reference = str(step["uses"])
        step["uses"] = _same_style(step["uses"], action.reference)
        changes.append(f"Replaced {reference} with {action.reference} in job {job_id}.")
        inputs = step.get("with")
        if isinstance(inputs, CommentedMap):
            for key in [str(key) for key in inputs]:
                if key not in kept or key not in action.allowed:
                    _remove(inputs, key)
                    changes.append(f"Dropped input {key}.")
    return changes


def _rename_expressions(document: CommentedMap) -> list[str]:
    """Rewrite github.* and runner.* names inside ${{ }} and in bare if conditions."""
    counts: dict[tuple[str, str], int] = {}

    def rename(match: re.Match[str]) -> str:
        if match[1]:
            replacement = f"inputs.{match[1]}"
        else:
            found = PLATFORM_NAMES[match[2]].get(match[3])
            if found is None:
                return match[0]
            replacement = found
        pair = (match[0], replacement)
        counts[pair] = counts.get(pair, 0) + 1
        return replacement

    def expression(source: str) -> str:
        # Quoted literals such as 'github.sha' are text, not names.
        parts, last = [], 0
        for literal in _QUOTED.finditer(source):
            parts += [_PLATFORM_NAME.sub(rename, source[last : literal.start()]), literal[0]]
            last = literal.end()
        return "".join([*parts, _PLATFORM_NAME.sub(rename, source[last:])])

    for container, key, value in _strings(document):
        if key == "if" and "${{" not in value:
            updated = expression(value)
        else:
            updated = _EXPRESSION.sub(lambda match: f"${{{{{expression(match[1])}}}}}", value)
        if updated != value:
            container[key] = _same_style(value, updated)
    return [
        f"Replaced {old} with {new} ({_places(count)})." for (old, new), count in counts.items()
    ]


def _rename_file_variables(jobs: list[tuple[str, CommentedMap]]) -> list[str]:
    counts: dict[str, int] = {}

    def rename(match: re.Match[str]) -> str:
        counts[match[1]] = counts.get(match[1], 0) + 1
        return f"RELAY_{match[1]}"

    for _, job in jobs:
        for _, step in _steps(job):
            script = step.get("run")
            if isinstance(script, str) and FILE_VARIABLES.search(script):
                step["run"] = _same_style(script, FILE_VARIABLES.sub(rename, script))
    return [
        f"Replaced $GITHUB_{name} with $RELAY_{name} ({_places(count)})."
        for name, count in counts.items()
    ]


def _places(count: int) -> str:
    return f"{count} place" if count == 1 else f"{count} places"


def _strings(node: object) -> Iterator[tuple[Any, Any, str]]:
    """Every string value with its container and key, in document order."""
    if isinstance(node, CommentedMap):
        items: list[tuple[Any, Any]] = list(node.items())
    elif isinstance(node, CommentedSeq):
        items = list(enumerate(node))
    else:
        return
    for key, value in items:
        if isinstance(value, str):
            yield node, key, value
        else:
            yield from _strings(value)


def _same_style(original: object, text: str) -> str:
    """Keep a scalar's quoting or block style when its text changes."""
    if type(original) is str or not isinstance(original, str):
        return text
    # ruamel's literal and folded strings keep the comment after | or > here.
    replacement: Any = type(original)(text)
    comment = getattr(original, "comment", None)
    if comment is not None:
        replacement.comment = comment
    return replacement


def _block(node: object) -> bool:
    return (
        isinstance(node, (CommentedMap, CommentedSeq)) and bool(node) and not node.fa.flow_style()
    )


def _last_slot(container: Any, key: Any) -> tuple[Any, Any, int]:
    """Where ruamel keeps the comment that follows an entry's last line."""
    while True:
        value = container[key]
        if not _block(value):
            return container, key, 2 if isinstance(container, CommentedMap) else 0
        container = value
        key = list(value)[-1] if isinstance(value, CommentedMap) else len(value) - 1


def _remove(container: Any, key: Any) -> None:
    """Delete one entry, keeping the full-line comments that followed it."""
    keys = list(container) if isinstance(container, CommentedMap) else list(range(len(container)))
    position = keys.index(key)
    holder, slot, index = _last_slot(container, key)
    comments = holder.ca.items.get(slot)
    token = comments[index] if comments and len(comments) > index else None
    # The first line is the removed line's own end-of-line comment.
    tail = token.value.partition("\n")[2] if token is not None else ""
    del container[key]
    if "#" not in tail:
        return
    if position == 0:
        # The parent shares this list for the comments above the first entry.
        comment = container.ca.comment
        if comment is not None and comment[1] is not None:
            comment[1].append(_comment(tail))
        elif comment is not None and comment[0] is not None:
            # The parent key's end-of-line comment is emitted in place of the list.
            comment[0].value += tail
        else:
            container.ca.comment = [None, [_comment(tail)]]
        return
    holder, slot, index = _last_slot(container, keys[position - 1])
    comments = holder.ca.items.setdefault(slot, [None, None, None, None])
    if comments[index] is None:
        comments[index] = _comment("\n" + tail)
    else:
        comments[index].value = comments[index].value + tail


def _comment(text: str) -> CommentToken:
    return CommentToken(text, CommentMark(0), None)


def _layout(document: CommentedMap) -> tuple[int, int]:
    """The source's mapping indent and sequence dash offset, such as (2, 2)."""
    mapping: int | None = None
    offset: int | None = None
    pending: list[object] = [document]
    while pending and (mapping is None or offset is None):
        node = pending.pop(0)
        if isinstance(node, CommentedSeq):
            pending.extend(node)
            continue
        if not isinstance(node, CommentedMap):
            continue
        for key, value in node.items():
            pending.append(value)
            if not _block(value):
                continue
            key_line, key_column = node.lc.key(key)
            value_line, value_column = node.lc.value(key)
            if value_line <= key_line:
                continue
            if isinstance(value, CommentedMap) and mapping is None:
                mapping = value_column - key_column
            elif isinstance(value, CommentedSeq) and offset is None:
                offset = value_column - key_column
    mapping = mapping if mapping is not None and mapping > 0 else 2
    offset = offset if offset is not None and offset >= 0 else 0
    return mapping, offset


def _dump(document: CommentedMap, parser: YAML) -> str:
    mapping, offset = _layout(document)
    parser.indent(mapping=mapping, sequence=offset + 2, offset=offset)
    # Never fold long lines such as scripts and conditions.
    parser.width = 1_000_000
    stream = StringIO()
    parser.dump(document, stream)
    return stream.getvalue()


__all__ = ["ImportResult", "convert_github_workflow"]
