from __future__ import annotations

import subprocess
from pathlib import Path


def _run_git(path: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=path,
        capture_output=True,
        text=True,
        check=False,
    )


def is_git_repo(path: str) -> bool:
    repo_path = Path(path)
    if (repo_path / ".git").exists():
        return True
    result = _run_git(path, "rev-parse", "--is-inside-work-tree")
    return result.returncode == 0 and result.stdout.strip() == "true"


def get_head_commit(path: str) -> str | None:
    result = _run_git(path, "rev-parse", "HEAD")
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def get_current_branch(path: str) -> str | None:
    result = _run_git(path, "branch", "--show-current")
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def create_branch(path: str, branch_name: str, from_commit: str | None) -> str:
    target = from_commit or "HEAD"
    result = _run_git(path, "checkout", "-B", branch_name, target)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "git checkout failed")
    return branch_name
