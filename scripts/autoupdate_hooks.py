#!/usr/bin/env python3
"""Update hooks without replacing a stable release with an older release."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import subprocess
import sys

from ruamel.yaml import YAML
from ruamel.yaml.nodes import MappingNode, Node, ScalarNode, SequenceNode

RELEASE = re.compile(r"v?([0-9]+(?:\.[0-9]+){1,3})")


def release_version(revision: str) -> tuple[int, ...] | None:
    """Recognize numeric release tags, leaving other Git refs to pre-commit."""
    match = RELEASE.fullmatch(revision)
    if match is None:
        return None
    parts = tuple(int(part) for part in match[1].split("."))
    return parts + (0,) * (4 - len(parts))


def field(mapping: MappingNode, name: str) -> Node | None:
    """Read a mapping field while retaining its exact source location."""
    for key, value in mapping.value:
        if isinstance(key, ScalarNode) and key.value == name:
            return value
    return None


def revisions(source: str) -> list[tuple[str, ScalarNode]]:
    """Locate remote repository revisions in their declaration order."""
    document = YAML(typ="safe").compose(source)
    if not isinstance(document, MappingNode):
        message = "Hook configuration must be a mapping"
        raise TypeError(message)
    repositories = field(document, "repos")
    if not isinstance(repositories, SequenceNode):
        message = "Hook configuration must contain a repos list"
        raise TypeError(message)
    result: list[tuple[str, ScalarNode]] = []
    for repository in repositories.value:
        if not isinstance(repository, MappingNode):
            message = "Hook repository must be a mapping"
            raise TypeError(message)
        url = field(repository, "repo")
        revision = field(repository, "rev")
        if isinstance(url, ScalarNode) and isinstance(revision, ScalarNode):
            result.append((url.value, revision))
    return result


def preserve_releases(original: str, candidate: str) -> tuple[str, list[str]]:
    """Restore downgraded numeric tags without rewriting YAML or comments."""
    replacements: list[tuple[int, int, str]] = []
    notices: list[str] = []
    for (old_repo, old), (new_repo, new) in zip(
        revisions(original), revisions(candidate), strict=True
    ):
        if old_repo != new_repo:
            message = "Autoupdate changed hook repository ordering"
            raise ValueError(message)
        old_version = release_version(old.value)
        new_version = release_version(new.value)
        if old_version is not None and new_version is not None and new_version < old_version:
            replacement = original[old.start_mark.index : old.end_mark.index]
            replacements.append((new.start_mark.index, new.end_mark.index, replacement))
            notices.append(f"{old_repo}: retained {old.value} instead of {new.value}")
    for start, end, replacement in reversed(replacements):
        candidate = candidate[:start] + replacement + candidate[end:]
    return candidate, notices


def update_hooks(config: Path) -> int:
    """Run the normal updater and keep previously selected newer releases."""
    original = config.read_text(encoding="utf-8")
    # The executable is this interpreter, the module is installed, and no shell runs.
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-m", "pre_commit", "autoupdate", "--config", str(config)],
        check=False,
    )
    if result.returncode:
        return result.returncode
    candidate = config.read_text(encoding="utf-8")
    updated, notices = preserve_releases(original, candidate)
    if updated != candidate:
        config.write_text(updated, encoding="utf-8")
    for notice in notices:
        print(notice)
    return 0


def main(argv: list[str]) -> int:
    """Update the selected hook configuration."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path(".pre-commit-config.yaml"))
    arguments = parser.parse_args(argv)
    return update_hooks(arguments.config)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
