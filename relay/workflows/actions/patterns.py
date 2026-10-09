"""Ordered GitHub glob filters and bounded, root-safe file selection."""

from __future__ import annotations

from collections.abc import Sequence
import os
from pathlib import Path
import re

from relay.errors import PathSafetyError, WorkflowValidationError


def pattern_regex(pattern: str, *, file_glob: bool = False) -> re.Pattern[str]:
    """Compile the documented Actions filter language, including ordered '!'."""
    pattern = pattern.removeprefix("/").removeprefix("./")
    if len(pattern) > 4096 or "\x00" in pattern:
        message = "Invalid or oversized filter pattern."
        raise WorkflowValidationError(message)
    if any(part == ".." for part in pattern.split("/")):
        message = "A filter pattern escapes the workspace."
        raise PathSafetyError(message)
    result = []
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "\\":
            if index + 1 >= len(pattern):
                message = "A filter escape must precede a character."
                raise WorkflowValidationError(message)
            result.append(re.escape(pattern[index + 1]))
            index += 2
        elif pattern[index : index + 3] == "**/":
            result.append("(?:.*/)?")
            index += 3
        elif pattern[index : index + 2] == "**":
            result.append(".*")
            index += 2
        elif char == "*":
            result.append("[^/]*")
            index += 1
        elif char == "?" and file_glob:
            result.append("[^/]")
            index += 1
        elif char in {"?", "+"} and result:
            result.append(char)
            index += 1
        elif char == "[" and "]" in pattern[index + 1 :]:
            end = pattern.index("]", index + 1)
            characters = pattern[index + 1 : end]
            if not characters or any(item in characters for item in {"\\", "[", "/"}):
                message = "Invalid character range in filter."
                raise WorkflowValidationError(message)
            if file_glob and characters.startswith("!"):
                characters = "^" + characters[1:]
            result.append("[" + characters + "]")
            index = end + 1
        else:
            result.append(re.escape(char))
            index += 1
    try:
        return re.compile("^" + "".join(result) + "$")
    except re.error:
        message = "Invalid filter pattern."
        raise WorkflowValidationError(message) from None


def matches(value: str, patterns: Sequence[str], *, file_glob: bool = False) -> bool:
    included = False
    for pattern in patterns:
        negative = pattern.startswith("!")
        if pattern_regex(pattern[1:] if negative else pattern, file_glob=file_glob).fullmatch(
            value
        ):
            included = not negative
    return included


def select_paths(root: Path, patterns: Sequence[str], *, files_only: bool = False) -> list[Path]:
    """Never follow links, traverse .git, or enumerate an unbounded tree."""
    root = root.resolve(strict=True)
    normalized = list(patterns)
    for pattern in normalized:
        pattern_regex(pattern.removeprefix("!"), file_glob=True)
    result = []
    count = 0
    for directory, folders, files in os.walk(root, followlinks=False):
        folders[:] = sorted(item for item in folders if item != ".git")
        for name in [*folders, *sorted(files)]:
            count += 1
            if count > 100_000:
                message = "File selection exceeds 100000 entries."
                raise WorkflowValidationError(message)
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink() or (bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)):
                if matches(relative, normalized, file_glob=True):
                    message = "File selection includes a symbolic link."
                    raise PathSafetyError(message)
                continue
            selected = matches(relative, normalized, file_glob=True)
            if not selected:
                # Selecting a directory includes its files; exclusions still apply last.
                parents = list(path.relative_to(root).parents)[:-1]
                selected = any(
                    matches(parent.as_posix(), normalized, file_glob=True) for parent in parents
                )
                if selected:
                    for pattern in normalized:
                        if pattern.startswith("!") and pattern_regex(
                            pattern[1:], file_glob=True
                        ).fullmatch(relative):
                            selected = False
            if selected and (not files_only or path.is_file()):
                result.append(path)
    return sorted(result, key=lambda path: path.relative_to(root).as_posix())
