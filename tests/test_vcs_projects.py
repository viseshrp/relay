"""Git isolation, retained evidence, commit protection, and project identity."""

from __future__ import annotations

from hashlib import sha256
import json
import os
from pathlib import Path

import pytest

from relay.errors import (
    ArtifactPreservationError,
    CommitValidationError,
    DirtyRepositoryError,
    GitError,
    ProjectDiscoveryError,
    ProjectRelinkError,
    WorktreeError,
)
from relay.projects import service
from relay.projects.discovery import discover_relay_root, git_root
from relay.projects.identity import canonical_path, identify_project
from relay.vcs import git as git_module
from relay.vcs.artifacts import preserve_attempt_evidence, preserve_then_reset, retained_attempt_ref
from relay.vcs.cleanliness import require_clean, status_porcelain
from relay.vcs.commits import (
    commits_between,
    current_head,
    is_ancestor,
    validate_reader_result,
    validate_writer_result,
)
from relay.vcs.git import git_executable, run_git, run_git_bytes, run_git_to_file
from relay.vcs.worktree import (
    create_primary_worktree,
    create_reader_worktree,
    remove_worktree,
    require_project_worktree,
    reset_worktree,
    run_branch,
)
from relay.web.repositories import DjangoProjectStore
from tests.support import git, init_repository, symlink_or_skip


@pytest.fixture
def repository(tmp_path: Path) -> Path:
    return init_repository(tmp_path / "repo & quoted 'name'")


def commit(repository: Path, name: str, text: str = "x") -> str:
    (repository / name).write_text(text, encoding="utf-8")
    git(repository, "add", name)
    git(repository, "commit", "-q", "-m", f"add {name}")
    return current_head(repository)


def test_launch_source_reads_the_branch_without_changing_owner_edits(repository: Path) -> None:
    git(repository, "branch", "-m", "launch/source")
    (repository / "loose.txt").write_text("owner edit", encoding="utf-8")
    before = status_porcelain(repository)
    source = service.project_launch_source(repository)
    assert source == service.ProjectLaunchSource("launch/source", current_head(repository))
    assert status_porcelain(repository) == before


def test_launch_source_reads_a_detached_head(repository: Path) -> None:
    head = current_head(repository)
    git(repository, "checkout", "--detach", head)
    assert service.project_launch_source(repository) == service.ProjectLaunchSource(None, head)


def test_launch_source_reports_an_unborn_branch(tmp_path: Path) -> None:
    repository = tmp_path / "unborn"
    repository.mkdir()
    git(repository, "init", "-q", "--initial-branch=main")
    assert service.project_launch_source(repository) == service.ProjectLaunchSource("main", None)


def test_launch_source_reports_git_failure_without_third_party_output(tmp_path: Path) -> None:
    with pytest.raises(GitError, match="could not read this project's Git source"):
        service.project_launch_source(tmp_path)


@pytest.mark.parametrize("mode", ["text", "bytes", "file"])
def test_git_handles_metacharacters_in_a_repository_path_as_one_operand(
    repository: Path, tmp_path: Path, mode: str
) -> None:
    expected = current_head(repository).encode()
    if mode == "file":
        output = tmp_path / "head"
        with output.open("wb") as stream:
            run_git_to_file(repository, ["rev-parse", "HEAD"], stream)
        actual = output.read_bytes()
    elif mode == "bytes":
        actual = run_git_bytes(repository, ["rev-parse", "HEAD"]).stdout
    else:
        actual = run_git(repository, ["rev-parse", "HEAD"]).stdout.encode()
    assert actual.strip() == expected


@pytest.mark.parametrize("mode", ["text", "bytes", "file"])
def test_unsuccessful_git_commands_raise_a_relay_error(
    repository: Path, tmp_path: Path, mode: str
) -> None:
    with pytest.raises(GitError):
        if mode == "file":
            with (tmp_path / "out").open("wb") as stream:
                run_git_to_file(repository, ["rev-parse", "no-such-ref"], stream)
        elif mode == "bytes":
            run_git_bytes(repository, ["rev-parse", "no-such-ref"])
        else:
            run_git(repository, ["rev-parse", "no-such-ref"])


@pytest.mark.parametrize("mode", ["text", "bytes", "file"])
def test_git_spawn_failures_do_not_leak_os_exceptions(
    repository: Path, tmp_path: Path, mode: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unavailable(*args: object, **kwargs: object) -> None:
        del args, kwargs
        message = "exec failed"
        raise OSError(message)

    monkeypatch.setattr(git_module.subprocess, "run", unavailable)
    with pytest.raises(GitError):
        if mode == "file":
            with (tmp_path / "out").open("wb") as stream:
                run_git_to_file(repository, ["status"], stream)
        elif mode == "bytes":
            run_git_bytes(repository, ["status"])
        else:
            run_git(repository, ["status"])


def test_missing_git_is_reported_as_a_relay_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))
    with pytest.raises(GitError):
        git_executable()


def test_cleanliness_includes_untracked_files(repository: Path) -> None:
    (repository / "loose.txt").write_text("x", encoding="utf-8")
    assert status_porcelain(repository) == ("?? loose.txt",)
    with pytest.raises(DirtyRepositoryError):
        require_clean(repository, stage="launch")


def test_a_checkout_from_another_project_cannot_be_used_for_execution(
    repository: Path,
    tmp_path: Path,
) -> None:
    other = init_repository(tmp_path / "other-project")
    with pytest.raises(WorktreeError):
        require_project_worktree(repository, other)
    require_project_worktree(repository, repository)


def test_a_writer_must_commit_its_changes(repository: Path) -> None:
    start = current_head(repository)
    (repository / "loose.txt").write_text("x", encoding="utf-8")
    with pytest.raises(CommitValidationError, match="uncommitted"):
        validate_writer_result(repository, start)


def test_a_writer_without_a_commit_is_rejected(repository: Path) -> None:
    with pytest.raises(CommitValidationError):
        validate_writer_result(repository, current_head(repository))


def test_an_explicit_writer_noop_keeps_the_same_head(repository: Path) -> None:
    head = current_head(repository)
    result = validate_writer_result(repository, head, allow_no_commit=True)
    assert (result.starting_head, result.ending_head, result.commit_count) == (head, head, 0)


@pytest.mark.parametrize(
    "name",
    [
        "PLAN_CHECKPOINT.json",
        "REVIEW_CHECKPOINT.json",
        "AUDIT_CHECKPOINT.json",
        "E2E_CHECKPOINT.json",
        "E2E_VERIFICATION.md",
    ],
)
def test_autonomous_run_reports_can_remain_uncommitted(repository: Path, name: str) -> None:
    head = current_head(repository)
    (repository / name).write_text('{"ready": false}\n', encoding="utf-8")

    result = validate_writer_result(repository, head, allow_no_commit=True)

    assert result.ending_head == head
    assert status_porcelain(repository) == (f"?? {name}",)


@pytest.mark.parametrize("name", ["settings.json", "nested/PLAN_CHECKPOINT.json"])
def test_other_uncommitted_json_remains_a_writer_error(repository: Path, name: str) -> None:
    path = repository / name
    path.parent.mkdir(exist_ok=True)
    path.write_text('{"ready": false}\n', encoding="utf-8")

    with pytest.raises(CommitValidationError):
        validate_writer_result(repository, current_head(repository), allow_no_commit=True)


def test_staged_checkpoint_changes_remain_a_writer_error(repository: Path) -> None:
    name = "PLAN_CHECKPOINT.json"
    (repository / name).write_text('{"ready": false}\n', encoding="utf-8")
    git(repository, "add", name)

    with pytest.raises(CommitValidationError):
        validate_writer_result(repository, current_head(repository), allow_no_commit=True)


def test_writer_commit_attribution_lists_descendants_in_order(repository: Path) -> None:
    start = current_head(repository)
    first = commit(repository, "a.txt")
    second = commit(repository, "b.txt")
    result = validate_writer_result(repository, start)
    assert (result.ending_head, result.commit_count) == (second, 2)
    assert commits_between(repository, start, second) == (first, second)


def test_a_writer_cannot_move_to_an_unrelated_history(repository: Path) -> None:
    start = current_head(repository)
    git(repository, "checkout", "-q", "--orphan", "elsewhere")
    git(repository, "commit", "-q", "-m", "unrelated")
    with pytest.raises(CommitValidationError):
        validate_writer_result(repository, start)


@pytest.mark.parametrize("change", ["uncommitted", "committed"])
def test_a_reader_cannot_change_its_attributed_worktree(repository: Path, change: str) -> None:
    start = current_head(repository)
    if change == "committed":
        commit(repository, "changed.txt")
    else:
        (repository / "changed.txt").write_text("x", encoding="utf-8")
    with pytest.raises(CommitValidationError):
        validate_reader_result(repository, start)


def test_ancestry_distinguishes_descendants_from_ancestors(repository: Path) -> None:
    start = current_head(repository)
    end = commit(repository, "a.txt")
    assert is_ancestor(repository, start, end)
    assert not is_ancestor(repository, end, start)


def test_unknown_ancestry_is_a_git_error(repository: Path) -> None:
    with pytest.raises(GitError):
        is_ancestor(repository, "unknown", current_head(repository))


def test_primary_and_reader_worktrees_use_the_recorded_commit(
    repository: Path, tmp_path: Path
) -> None:
    head = current_head(repository)
    branch, primary, resolved = create_primary_worktree(
        repository, "run-1", head, root=tmp_path / "trees"
    )
    reader, reader_head = create_reader_worktree(repository, primary, "attempt-1", resolved)
    assert branch == run_branch("run-1")
    assert resolved == reader_head == head
    assert reader.parent == primary and (reader / "README.md").is_file()
    remove_worktree(repository, reader)
    assert not reader.exists()


@pytest.mark.parametrize("collision", ["branch", "path"])
def test_primary_worktree_creation_cannot_replace_existing_state(
    repository: Path, tmp_path: Path, collision: str
) -> None:
    root = tmp_path / "trees"
    if collision == "path":
        (root / "run-1").mkdir(parents=True)
    else:
        git(repository, "branch", run_branch("run-1"))
    with pytest.raises(WorktreeError):
        create_primary_worktree(repository, "run-1", current_head(repository), root=root)


def test_reader_worktree_creation_cannot_replace_existing_state(
    repository: Path, tmp_path: Path
) -> None:
    head = current_head(repository)
    _branch, primary, _resolved = create_primary_worktree(
        repository, "run-1", head, root=tmp_path / "trees"
    )
    create_reader_worktree(repository, primary, "attempt-1", head)
    with pytest.raises(WorktreeError):
        create_reader_worktree(repository, primary, "attempt-1", head)


def test_reset_removes_uncommitted_files_after_protecting_the_head(repository: Path) -> None:
    protected = current_head(repository)
    end = commit(repository, "committed.txt")
    (repository / "scratch.txt").write_text("x", encoding="utf-8")
    assert reset_worktree(repository, end, protected_head=protected) == end
    assert not (repository / "scratch.txt").exists()


def test_reset_cannot_discard_a_successful_writer_commit(repository: Path) -> None:
    start = current_head(repository)
    protected = commit(repository, "committed.txt")
    with pytest.raises(WorktreeError):
        reset_worktree(repository, start, protected_head=protected)
    assert current_head(repository) == protected


@pytest.mark.parametrize("identifier", ["../escape", ".", "..", "-option", "a/b"])
def test_unsafe_run_ids_are_rejected(identifier: str) -> None:
    with pytest.raises(WorktreeError):
        run_branch(identifier)
    with pytest.raises(ArtifactPreservationError):
        retained_attempt_ref(identifier, "attempt")


@pytest.mark.parametrize("kind", ["commit", "diff", "untracked", "declared"])
def test_evidence_preservation_retains_bytes_and_integrity_metadata(
    repository: Path, tmp_path: Path, kind: str
) -> None:
    start = current_head(repository)
    declared = {}
    if kind == "commit":
        ending = commit(repository, "committed.txt")
        name = "commits"
        expected = f"{ending}\n".encode()
    elif kind == "diff":
        (repository / "README.md").write_text("changed\n", encoding="utf-8")
        name = "worktree_diff"
        expected = run_git_bytes(repository, ["diff", "--binary", "HEAD", "--"]).stdout
    elif kind == "untracked":
        (repository / "notes").mkdir()
        (repository / "notes/new.txt").write_text("untracked", encoding="utf-8")
        name, expected = "notes/new.txt", b"untracked"
    else:
        (repository / "report.txt").write_text("Ready: Yes", encoding="utf-8")
        name, expected = "ready", b"Ready: Yes"
        declared = {name: "report.txt"}

    result = preserve_attempt_evidence(
        repository,
        repository,
        "run-1",
        "attempt-1",
        start,
        declared_artifacts=declared,
        root=tmp_path / "evidence",
    )

    retained = next(file for file in result.files if file.name == name)
    assert Path(retained.retained_path).read_bytes() == expected
    assert (retained.sha256, retained.bytes) == (sha256(expected).hexdigest(), len(expected))
    manifest = json.loads((result.directory / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["retained_ref"] == retained_attempt_ref("run-1", "attempt-1")
    assert git(repository, "rev-parse", result.retained_ref) == result.ending_head


def test_untracked_symlinks_preserve_the_link_target_text(repository: Path, tmp_path: Path) -> None:
    link = repository / "link.txt"
    symlink_or_skip(link, repository / "README.md")
    target_text = os.readlink(link)
    result = preserve_attempt_evidence(
        repository,
        repository,
        "run-1",
        "attempt-1",
        current_head(repository),
        root=tmp_path / "evidence",
    )
    retained = next(file for file in result.files if file.name == "link.txt")
    assert retained.kind == "untracked_symlink_target"
    assert Path(retained.retained_path).read_text(encoding="utf-8") == target_text


@pytest.mark.parametrize(
    "declared", [{"ready": "missing.txt"}, {"ready": "../outside.txt"}, {"bad name": "README.md"}]
)
def test_failed_preservation_removes_partial_staging_but_keeps_the_commit_ref(
    repository: Path, tmp_path: Path, declared: dict[str, str]
) -> None:
    root = tmp_path / "evidence"
    head = current_head(repository)
    with pytest.raises(ArtifactPreservationError):
        preserve_attempt_evidence(
            repository,
            repository,
            "run-1",
            "attempt-1",
            head,
            declared_artifacts=declared,
            root=root,
        )
    assert not list((root / "run-1").iterdir())
    assert git(repository, "rev-parse", retained_attempt_ref("run-1", "attempt-1")) == head


def test_existing_evidence_cannot_be_overwritten(repository: Path, tmp_path: Path) -> None:
    start = current_head(repository)
    root = tmp_path / "evidence"
    preserve_attempt_evidence(repository, repository, "run-1", "attempt-1", start, root=root)
    with pytest.raises(ArtifactPreservationError):
        preserve_attempt_evidence(repository, repository, "run-1", "attempt-1", start, root=root)


def test_preserve_then_reset_retains_the_discarded_commit_and_file(
    repository: Path, tmp_path: Path
) -> None:
    start = current_head(repository)
    end = commit(repository, "work.txt")
    (repository / "scratch.txt").write_text("uncommitted", encoding="utf-8")
    result = preserve_then_reset(
        repository,
        repository,
        "run-1",
        "attempt-1",
        start,
        protected_head=start,
        root=tmp_path / "evidence",
    )
    assert current_head(repository) == start
    assert git(repository, "rev-parse", result.retained_ref) == end
    retained = next(file for file in result.files if file.name == "scratch.txt")
    assert Path(retained.retained_path).read_bytes() == b"uncommitted"


def test_a_preservation_failure_prevents_reset(repository: Path, tmp_path: Path) -> None:
    start = current_head(repository)
    end = commit(repository, "work.txt")
    with pytest.raises(ArtifactPreservationError):
        preserve_then_reset(
            repository,
            repository,
            "run-1",
            "attempt-1",
            start,
            protected_head=start,
            declared_artifacts={"missing": "missing.txt"},
            root=tmp_path / "evidence",
        )
    assert current_head(repository) == end


def test_project_discovery_finds_the_nearest_relay_root_from_a_file(repository: Path) -> None:
    service.initialize_project(repository)
    nested = repository / "src/deep"
    nested.mkdir(parents=True)
    file_path = nested / "file.py"
    file_path.write_text("", encoding="utf-8")
    assert discover_relay_root(file_path) == (repository / ".relay").resolve()


def test_project_discovery_defaults_to_the_current_directory(
    repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service.initialize_project(repository)
    monkeypatch.chdir(repository)
    assert discover_relay_root() == (repository / ".relay").resolve()


def test_a_non_git_directory_is_not_a_project(tmp_path: Path) -> None:
    with pytest.raises(ProjectDiscoveryError):
        git_root(tmp_path)


def test_a_git_repository_without_relay_metadata_is_not_an_initialized_project(
    repository: Path,
) -> None:
    with pytest.raises(ProjectDiscoveryError):
        discover_relay_root(repository)


def test_initialization_is_idempotent(repository: Path) -> None:
    first = service.initialize_project(repository)
    second = service.initialize_project(repository)
    assert first.created and not second.created
    assert (first.relay_root / "prompts/prompt.md").read_text(encoding="utf-8") == ""
    assert not list(repository.glob(".relay-init-*"))


def test_atomic_initialization_cleans_a_lost_race(
    repository: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def winner(self: Path, target: Path) -> Path:
        del self
        target.mkdir()
        raise FileExistsError

    monkeypatch.setattr(Path, "replace", winner)
    assert not service.initialize_project(repository).created
    assert not list(repository.glob(".relay-init-*"))


def test_project_identity_is_canonical_and_registered_once(repository: Path) -> None:
    store = DjangoProjectStore()
    first = service.register_current_project(store, repository)
    second = service.register_current_project(store, repository)
    identity = identify_project(repository)
    assert first.id == second.id
    assert identity.canonical_path == canonical_path(repository)
    assert [record.id for record in service.list_registered_projects(store)] == [first.id]


@pytest.mark.parametrize("reason", ["same", "registered", "unknown"])
def test_invalid_project_relinks_are_rejected(
    repository: Path, tmp_path: Path, reason: str
) -> None:
    store = DjangoProjectStore()
    service.register_current_project(store, repository)
    if reason == "same":
        old, new = repository, repository
    else:
        other = init_repository(tmp_path / "other")
        service.register_current_project(store, other)
        old, new = (tmp_path / "unknown" if reason == "unknown" else repository), other
    with pytest.raises(ProjectRelinkError):
        service.relink_project(store, old, new)
