"""Verify Relay distribution contents without extracting untrusted archives."""

from __future__ import annotations

import argparse
from collections.abc import Iterable, Sequence
from pathlib import Path, PurePosixPath
import tarfile
import zipfile

_STARTER_FILES = frozenset(
    f"relay/workflows/starters/{name}"
    for name in (
        "ask-agent.yaml",
        "ask-agent.md",
        "plan-approve-implement.yaml",
        "plan.md",
        "implement.md",
        "implement-and-test.yaml",
        "review-branch.yaml",
        "review-branch.md",
        "fix-tests.yaml",
        "fix-tests.md",
        "write-docs.yaml",
        "write-docs.md",
    )
)


def _relative_sdist_names(names: Iterable[str]) -> tuple[str, ...]:
    relative: list[str] = []
    for name in names:
        parts = PurePosixPath(name).parts
        if len(parts) > 1:
            relative.append(PurePosixPath(*parts[1:]).as_posix())
    return tuple(relative)


def _archive_names(path: Path) -> tuple[str, ...]:
    if path.suffix == ".whl":
        with zipfile.ZipFile(path) as archive:
            return tuple(archive.namelist())
    if path.name.endswith(".tar.gz"):
        with tarfile.open(path, mode="r:gz") as archive:
            return _relative_sdist_names(member.name for member in archive.getmembers())
    message = f"Unsupported distribution archive: {path}"
    raise ValueError(message)


def _looks_like_template(name: str) -> bool:
    path = PurePosixPath(name.lower())
    if path.suffix in {".yaml", ".yml"}:
        return True
    if any(
        part in {".relay", "templates", "workflow_templates", "prompt_templates", "starters"}
        for part in path.parts
    ):
        return True
    return "prompt" in path.stem and path.suffix in {".md", ".txt"}


def _check_wheel(path: Path, names: tuple[str, ...]) -> None:
    if any(name.endswith(".map") or "/.vite/" in name for name in names):
        message = f"{path.name} contains frontend source maps or build manifests"
        raise RuntimeError(message)
    if "relay/static/index.html" not in names:
        message = f"{path.name} does not contain relay/static/index.html"
        raise RuntimeError(message)
    if not any(name.startswith("relay/static/assets/") for name in names):
        message = f"{path.name} does not contain compiled frontend assets"
        raise RuntimeError(message)


def _check_sdist(path: Path, names: tuple[str, ...]) -> None:
    generated_roots = (
        "frontend/node_modules/",
        "frontend/test-results/",
        "frontend/playwright-report/",
        "relay/static/",
    )
    if any(name.startswith(generated_roots) for name in names):
        message = f"{path.name} contains generated frontend dependencies or artifacts"
        raise RuntimeError(message)
    required = {
        "frontend/package.json",
        "frontend/package-lock.json",
        "hatch_build.py",
        "docs/getting-started.md",
        "docs/coming-from-github-actions.md",
        "docs/keyboard-shortcuts.md",
    }
    missing = sorted(required.difference(names))
    if missing:
        message = f"{path.name} is missing wheel-from-sdist inputs: {', '.join(missing)}"
        raise RuntimeError(message)
    if any(name.startswith("certification/") for name in names):
        message = f"{path.name} contains non-packaged certification evidence"
        raise RuntimeError(message)


def check_distribution(path: Path) -> None:
    """Validate one wheel or source distribution."""
    names = _archive_names(path)
    templates = sorted(
        name for name in names if _looks_like_template(name) and name not in _STARTER_FILES
    )
    if templates:
        message = f"{path.name} contains forbidden workflow or prompt templates: {templates}"
        raise RuntimeError(message)
    if path.suffix == ".whl":
        _check_wheel(path, names)
    else:
        _check_sdist(path, names)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("archives", nargs="+", type=Path)
    options = parser.parse_args(argv)
    for archive in options.archives:
        check_distribution(archive)
        print(f"Distribution content passed: {archive}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
