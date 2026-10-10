"""Commit previews protect reviewed bytes and preserve the original failure."""

from collections.abc import Sequence
from pathlib import Path

import pytest

from relay.errors import GitError, PermissionFlowError, WorkflowValidationError
from relay.vcs.git import GitResult
from relay.workflows import publication
from tests.support import RelayProject, git
from tests.test_editor_recovery import SOURCE


@pytest.fixture
def sources(project: RelayProject) -> tuple[RelayProject, Path]:
    project.write_workflow("check", SOURCE)
    project.commit("Save launched workflow")
    return project, project.write(".relay/workflows/new.yaml", SOURCE.replace("Recovery", "New"))


def test_preview_skips_invalid_unrelated_sources_with_a_notice(
    sources: tuple[RelayProject, Path],
) -> None:
    project, path = sources
    invalid = project.write(".relay/workflows/invalid.yaml", "jobs: [")
    preview = publication.preview_workflow_commit(project.relay_root, "check.yaml")
    assert [item["path"] for item in preview["files"]] == [
        path.relative_to(project.repository).as_posix()
    ]
    assert "invalid.yaml" in str(preview["notices"])
    with pytest.raises(WorkflowValidationError):
        publication.preview_workflow_commit(project.relay_root, invalid.name)


@pytest.mark.parametrize("when", ["before-add", "after-add"])
def test_only_the_reviewed_staged_blob_can_be_committed(
    sources: tuple[RelayProject, Path], monkeypatch: pytest.MonkeyPatch, when: str
) -> None:
    project, path = sources
    preview = publication.preview_workflow_commit(project.relay_root, "check.yaml")
    original = publication.run_git
    reviewed = path.read_bytes()
    foreign = reviewed.replace(b"New", b"Unreviewed")

    def racing_add(repository: Path, arguments: Sequence[str], *, check: bool = True) -> GitResult:
        if arguments[0] == "add" and when == "before-add":
            path.write_bytes(foreign)
        result = original(repository, arguments, check=check)
        if arguments[0] == "add" and when == "after-add":
            path.write_bytes(foreign)
        return result

    monkeypatch.setattr(publication, "run_git", racing_add)
    hashes = {item["path"]: item["hash"] for item in preview["files"]}
    if when == "before-add":
        with pytest.raises(PermissionFlowError):
            publication.commit_workflow_sources(
                project.relay_root, "check.yaml", preview["head"], hashes
            )
        assert git(project.repository, "rev-parse", "HEAD") == preview["head"]
    else:
        publication.commit_workflow_sources(
            project.relay_root, "check.yaml", preview["head"], hashes
        )
        assert git(
            project.repository, "show", "HEAD:.relay/workflows/new.yaml"
        ).encode() == reviewed.rstrip(b"\n")
    assert path.read_bytes() == foreign
    assert git(project.repository, "diff", "--cached", "--name-only") == ""


def test_failed_index_cleanup_does_not_mask_the_original_error(
    sources: tuple[RelayProject, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    project, _ = sources
    preview = publication.preview_workflow_commit(project.relay_root, "check.yaml")

    def failed_git(repository: Path, arguments: Sequence[str], *, check: bool = True) -> GitResult:
        del repository, check
        raise GitError("original failure" if arguments[0] == "add" else "cleanup failure")

    monkeypatch.setattr(publication, "run_git", failed_git)
    with pytest.raises(GitError, match="original failure"):
        publication.commit_workflow_sources(
            project.relay_root,
            "check.yaml",
            preview["head"],
            {item["path"]: item["hash"] for item in preview["files"]},
        )
