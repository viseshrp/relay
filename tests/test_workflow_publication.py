"""Commit previews protect reviewed bytes and preserve the original failure."""

from collections.abc import Sequence
from pathlib import Path

import pytest

from relay.errors import GitError, PermissionFlowError, WorkflowValidationError
from relay.vcs.git import GitBytesResult, GitResult, run_git_bytes
from relay.workflows import publication
from tests.support import RelayProject, git
from tests.test_editor_recovery import SOURCE


@pytest.fixture
def sources(project: RelayProject) -> tuple[RelayProject, Path]:
    project.write_workflow("check", SOURCE)
    project.commit("Save launched workflow")
    return project, project.write(".relay/workflows/new.yaml", SOURCE.replace("Recovery", "New"))


def test_selected_untracked_workflow_and_prompt_can_be_reviewed_and_committed(
    project: RelayProject,
) -> None:
    workflow = project.relay_root / "workflows/new.yaml"
    text = (
        "jobs:\n  review:\n    steps:\n      - uses: relay/agent@v1\n"
        "        with:\n          prompt-files: prompts/review.md\n"
    )
    project.write(".relay/workflows/new.yaml", text)
    prompt = project.write(".relay/prompts/review.md", "Review the code.\n")
    report = project.write("REVIEW.md", "Owner review notes\n")
    unused = project.write(".relay/prompts/unused.md", "Owner instructions\n")
    preview = publication.preview_workflow_commit(project.relay_root, "new.yaml")
    expected = {
        path.relative_to(project.repository).as_posix(): path.read_bytes()
        for path in (workflow, prompt)
    }
    assert {item["path"]: item["text"].encode() for item in preview["files"]} == expected
    publication.commit_workflow_sources(
        project.relay_root,
        "new.yaml",
        preview["head"],
        {item["path"]: item["hash"] for item in preview["files"]},
    )
    for name, raw in expected.items():
        assert run_git_bytes(project.repository, ["show", f"HEAD:{name}"]).stdout == raw
    assert set(
        git(
            project.repository, "diff-tree", "--no-commit-id", "--name-only", "-r", "HEAD"
        ).splitlines()
    ) == set(expected)
    assert git(project.repository, "diff", "--cached", "--name-only") == ""
    assert report.read_text() == "Owner review notes\n"
    assert unused.read_text() == "Owner instructions\n"
    assert publication.preview_workflow_commit(project.relay_root, "new.yaml")["files"] == []


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


@pytest.mark.parametrize("autocrlf", ["false", "true"])
@pytest.mark.parametrize("newline", [b"\n", b"\r\n"])
def test_reviewed_sources_follow_git_newline_conversion(
    sources: tuple[RelayProject, Path], autocrlf: str, newline: bytes
) -> None:
    project, path = sources
    git(project.repository, "config", "core.autocrlf", autocrlf)
    raw = path.read_bytes().replace(b"\n", newline)
    path.write_bytes(raw)
    preview = publication.preview_workflow_commit(project.relay_root, "check.yaml")
    publication.commit_workflow_sources(
        project.relay_root,
        "check.yaml",
        preview["head"],
        {item["path"]: item["hash"] for item in preview["files"]},
    )
    committed = run_git_bytes(project.repository, ["show", "HEAD:.relay/workflows/new.yaml"])
    assert committed.stdout == (raw.replace(b"\r\n", b"\n") if autocrlf == "true" else raw)
    assert path.read_bytes() == raw
    assert git(project.repository, "diff", "--cached", "--name-only") == ""


@pytest.mark.parametrize("autocrlf", ["false", "true"])
@pytest.mark.parametrize("when", ["before-add", "after-add"])
def test_only_the_reviewed_staged_blob_can_be_committed(
    sources: tuple[RelayProject, Path], monkeypatch: pytest.MonkeyPatch, when: str, autocrlf: str
) -> None:
    project, path = sources
    git(project.repository, "config", "core.autocrlf", autocrlf)
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
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
        committed = run_git_bytes(project.repository, ["show", "HEAD:.relay/workflows/new.yaml"])
        assert committed.stdout == (
            reviewed.replace(b"\r\n", b"\n") if autocrlf == "true" else reviewed
        )
    assert path.read_bytes() == foreign
    assert git(project.repository, "diff", "--cached", "--name-only") == ""


@pytest.mark.parametrize("autocrlf", ["false", "true"])
def test_an_edit_while_hashing_cannot_redefine_the_reviewed_sources(
    sources: tuple[RelayProject, Path], monkeypatch: pytest.MonkeyPatch, autocrlf: str
) -> None:
    project, path = sources
    git(project.repository, "config", "core.autocrlf", autocrlf)
    reviewed = path.read_bytes().replace(b"\n", b"\r\n")
    path.write_bytes(reviewed)
    preview = publication.preview_workflow_commit(project.relay_root, "check.yaml")
    foreign = reviewed.replace(b"New", b"Unreviewed")
    original = publication.run_git_bytes

    def racing_hash(
        repository: Path,
        arguments: Sequence[str],
        *,
        check: bool = True,
        input_bytes: bytes | None = None,
    ) -> GitBytesResult:
        if arguments[0] == "hash-object":
            path.write_bytes(foreign)
        return original(repository, arguments, check=check, input_bytes=input_bytes)

    monkeypatch.setattr(publication, "run_git_bytes", racing_hash)
    with pytest.raises(PermissionFlowError, match="changed the index"):
        publication.commit_workflow_sources(
            project.relay_root,
            "check.yaml",
            preview["head"],
            {item["path"]: item["hash"] for item in preview["files"]},
        )
    assert git(project.repository, "rev-parse", "HEAD") == preview["head"]
    assert git(project.repository, "diff", "--cached", "--name-only") == ""
    assert path.read_bytes() == foreign


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
