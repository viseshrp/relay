#!/usr/bin/env python3
"""Validate relative Markdown targets and GitHub-style heading fragments."""

from __future__ import annotations

from pathlib import Path
import re
import sys
from urllib.parse import unquote

LINK_PATTERN = re.compile(r"(?<!!)\[[^]]+\]\(([^)]+)\)")
HEADING_PATTERN = re.compile(r"^#{1,6}\s+(.+?)\s*#*$", re.MULTILINE)


def heading_slug(heading: str) -> str:
    """Map ``HTTP and SSE`` to GitHub's ``http-and-sse`` anchor shape."""
    lowered = heading.strip().lower()
    without_markup = re.sub(r"[`*_~]", "", lowered)
    without_punctuation = re.sub(r"[^\w\- ]", "", without_markup)
    return re.sub(r"[ -]+", "-", without_punctuation).strip("-")


def anchors(path: Path) -> set[str]:
    """Return unique rendered anchors, including GitHub's duplicate suffixes."""
    counts: dict[str, int] = {}
    rendered: set[str] = set()
    text = path.read_text(encoding="utf-8")
    for heading in HEADING_PATTERN.findall(text):
        base = heading_slug(heading)
        count = counts.get(base, 0)
        rendered.add(base if count == 0 else f"{base}-{count}")
        counts[base] = count + 1
    return rendered


def failures(path: Path) -> list[str]:
    """Return every unresolved local target found in one Markdown file."""
    problems: list[str] = []
    text = path.read_text(encoding="utf-8")
    for raw_target in LINK_PATTERN.findall(text):
        target = raw_target.split(maxsplit=1)[0].strip("<>")
        if target.startswith(("http://", "https://", "mailto:", "#")):
            if target.startswith("#") and target[1:] not in anchors(path):
                problems.append(f"{path}: missing anchor {target}")
            continue
        local, _, fragment = unquote(target).partition("#")
        destination = (path.parent / local).resolve()
        if not destination.exists():
            problems.append(f"{path}: missing target {local}")
            continue
        if (
            fragment
            and destination.suffix.lower() == ".md"
            and fragment not in anchors(destination)
        ):
            problems.append(f"{path}: missing anchor {fragment} in {local}")
    return problems


def main(argv: list[str]) -> int:
    """Validate the named Markdown files and print actionable failures."""
    paths = [Path(argument) for argument in argv[1:]]
    if not paths:
        print("usage: check_doc_links.py FILE.md [FILE.md ...]", file=sys.stderr)
        return 2
    problems = [problem for path in paths for problem in failures(path)]
    if problems:
        print("\n".join(problems), file=sys.stderr)
        return 1
    print(f"validated {len(paths)} Markdown file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
