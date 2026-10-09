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
        "ai-coding-workflow.yaml",
        "ai-coding-workflow/01_initial_exploration_any_model.md",
        "ai-coding-workflow/02_plan_critique_any_model.md",
        "ai-coding-workflow/03_plan_revision_verification_any_model.md",
        "ai-coding-workflow/04_opus_review_branch.md",
        "ai-coding-workflow/05_opus_verify_review_fixes.md",
        "ai-coding-workflow/06_opus_refresh_review_and_walkthrough.md",
        "ai-coding-workflow/07_human_code_walkthrough.md",
        "ai-coding-workflow/08_implement_human_followup_any_model.md",
        "ai-coding-workflow/09_write_focused_tests_any_model.md",
        "ai-coding-workflow/10_test_audit_any_model.md",
        "ai-coding-workflow/LICENSE",
        "ai-coding-workflow/action.yaml",
        "ai-coding-workflow/audit-routing.md",
        "ai-coding-workflow/interaction.md",
        "ai-coding-workflow/plan-cycle.yaml",
        "ai-coding-workflow/provenance.json",
        "ai-coding-workflow/review-cycle.yaml",
        "ai-coding-workflow/test-cycle.yaml",
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
    if "relay/static/index.html" not in names:
        message = f"{path.name} does not contain relay/static/index.html"
        raise RuntimeError(message)
    if not any(name.startswith("relay/static/assets/") for name in names):
        message = f"{path.name} does not contain compiled frontend assets"
        raise RuntimeError(message)


def _check_sdist(path: Path, names: tuple[str, ...]) -> None:
    required = {"frontend/package.json", "frontend/package-lock.json", "hatch_build.py"}
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
