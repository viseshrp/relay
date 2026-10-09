"""Launch previews use the execution boundary's exact Git exemptions."""

from __future__ import annotations

from pathlib import Path
import subprocess

import pytest

from relay.errors import DirtyRepositoryError
from relay.execution import preflight
from relay.execution.preflight import inspect_launch_cleanliness
from relay.projects.service import initialize_project
from relay.vcs.cleanliness import execution_status, status_porcelain
from relay.vcs.commits import current_head
from relay.web.models import Run
from tests.support import InlineEngine, RelayProject, git, init_repository, symlink_or_skip

COMMAND = "version: 1\nname: Check\nnodes:\n  check: {type: command, run: [git, status]}\n"


@pytest.mark.parametrize("kind", ["modified", "untracked", "staged", "staged-report", "deleted"])
def test_preview_explains_and_matches_launch_rejection(
    project: RelayProject, engine: InlineEngine, kind: str
) -> None:
    project.write_workflow("check", COMMAND)
    project.write("REVIEW.md", "Owner review\n")
    path = "README.md"
    if kind == "deleted":
        (project.repository / path).unlink()
    else:
        path = (
            "new code.py"
            if kind == "untracked"
            else "REVIEW.md"
            if kind == "staged-report"
            else path
        )
        project.write(path, "Owner changes\n")
        if kind.startswith("staged"):
            git(project.repository, "add", path)
    before = status_porcelain(project.repository)
    preview = inspect_launch_cleanliness(project.relay_root, "check")
    assert preview.clean is False
    assert preview.blocking_count == 1
    file = preview.files[0]
    assert file.path == path
    assert kind.removesuffix("-report") in file.reasons
    with pytest.raises(DirtyRepositoryError) as caught:
        engine.launch(project, "check")
    assert caught.value.context["changes"] == f"{file.status} {file.path}"
    assert status_porcelain(project.repository) == before
    assert not Run.objects.exists()
    assert not engine.tokens


def test_preview_preserves_validated_sources_and_launch_rechecks_new_changes(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write(".relay/workflows/check.yaml", COMMAND)
    report = project.write("REVIEW.md", "Owner review\n")
    head = current_head(project.repository)
    preview = inspect_launch_cleanliness(project.relay_root, "check")
    assert preview.clean
    assert {file.path: file.reasons for file in preview.files} == {
        ".relay/workflows/check.yaml": ("Captured workflow source",),
        "REVIEW.md": ("Root workflow report",),
    }
    run_id = engine.launch(project, "check")
    engine.drain(run_id)
    assert current_head(project.repository) == head
    assert report.read_text(encoding="utf-8") == "Owner review\n"
    assert git(project.repository, "diff", "--cached", "--name-only") == ""
    project.write("racing change.py", "unfinished\n")
    with pytest.raises(DirtyRepositoryError) as caught:
        engine.launch(project, "check")
    assert caught.value.context["changes"] == "?? racing change.py"
    assert Run.objects.count() == 1


def test_preview_exempts_only_the_validated_subworkflow_and_prompt_sources(
    project: RelayProject,
) -> None:
    project.write(
        ".relay/workflows/check.yaml",
        "version: 1\nname: Check\nnodes:\n  child: {type: subworkflow, workflow: child}\n",
    )
    project.write(
        ".relay/workflows/child.yaml",
        "version: 1\nname: Child\nnodes:\n"
        "  review: {type: agent, prompts: [{local: prompts/review.md}]}\n",
    )
    project.write(".relay/prompts/review.md", "Review the code.\n")
    project.write(".relay/prompts/unused.md", "Unused owner notes.\n")
    preview = inspect_launch_cleanliness(project.relay_root, "check")
    assert [file.path for file in preview.files if not file.allowed] == [".relay/prompts/unused.md"]
    assert {file.path for file in preview.files if file.allowed} == {
        ".relay/workflows/check.yaml",
        ".relay/workflows/child.yaml",
        ".relay/prompts/review.md",
    }


@pytest.mark.parametrize("line_ending", [b"\n", b"\r\n"])
def test_initial_setup_bytes_are_explained_without_exempting_owner_edits(
    tmp_path: Path, line_ending: bytes
) -> None:
    repository = init_repository(tmp_path / "repo")
    root = initialize_project(repository).relay_root
    starter = root / "workflows/workflow.yaml"
    starter.write_bytes(starter.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", line_ending))
    (root / "workflows/check.yaml").write_text(COMMAND, encoding="utf-8")
    preview = inspect_launch_cleanliness(root, "check")
    assert preview.clean
    assert [file.reasons for file in preview.files].count(("Unchanged setup file",)) == 2
    (root / "prompts/prompt.md").write_text("Owner notes\n", encoding="utf-8")
    edited = inspect_launch_cleanliness(root, "check")
    assert edited.blocking_count == 1
    assert edited.files[0].path == ".relay/prompts/prompt.md"
    assert edited.files[0].reasons == ("untracked",)


def test_nested_project_reports_use_the_project_prefix(tmp_path: Path) -> None:
    repository = init_repository(tmp_path / "repo")
    nested = repository / "nested"
    nested.mkdir()
    root = nested / ".relay"
    (root / "workflows").mkdir(parents=True)
    (root / "prompts").mkdir()
    (root / "workflows/check.yaml").write_text(COMMAND, encoding="utf-8")
    (nested / "REVIEW.md").write_text("Nested report\n", encoding="utf-8")
    (repository / "REVIEW.md").write_text("Outside project\n", encoding="utf-8")
    preview = inspect_launch_cleanliness(root, "check")
    assert [file.path for file in preview.files if not file.allowed] == ["REVIEW.md"]
    assert next(file for file in preview.files if file.path == "nested/REVIEW.md").allowed


def test_symlink_report_is_a_blocker(project: RelayProject, tmp_path: Path) -> None:
    project.write_workflow("check", COMMAND)
    outside = tmp_path / "outside.md"
    outside.write_text("Private content\n", encoding="utf-8")
    symlink_or_skip(project.repository / "REVIEW.md", outside)
    file = inspect_launch_cleanliness(project.relay_root, "check").files[0]
    assert file.allowed is False
    assert file.reasons == ("untracked", "symlink")
    assert "Private content" not in repr(file)


def test_renames_keep_both_unquoted_filenames(project: RelayProject) -> None:
    project.write("old name.txt", "original\n")
    project.commit("Add rename source")
    git(project.repository, "mv", "old name.txt", "new name.txt")
    change = execution_status(project.repository)[0]
    assert change.path == "new name.txt"
    assert change.original_path == "old name.txt"
    assert change.reasons == ("staged", "renamed")


def test_merge_conflicts_are_explained_without_reading_conflicted_content(
    project: RelayProject,
) -> None:
    git(project.repository, "checkout", "-b", "other")
    project.write("README.md", "Other branch\n")
    project.commit("Change other branch")
    git(project.repository, "checkout", "main")
    project.write("README.md", "Launch branch\n")
    project.commit("Change launch branch")
    with pytest.raises(subprocess.CalledProcessError):
        git(project.repository, "merge", "other")
    change = execution_status(project.repository)[0]
    assert change.allowed is False
    assert change.reasons == ("staged", "Git conflict")


def test_preview_bounds_files_but_counts_every_blocker(
    project: RelayProject, monkeypatch: pytest.MonkeyPatch
) -> None:
    project.write_workflow("check", COMMAND)
    for number in range(205):
        project.write(f"code/{number:03}.txt", "Owner bytes\n")
    preview = inspect_launch_cleanliness(project.relay_root, "check")
    assert (preview.blocking_count, len(preview.files), preview.truncated) == (205, 200, True)
    monkeypatch.setattr(preflight, "API_MAX_PAGE_BYTES", 250)
    bounded = inspect_launch_cleanliness(project.relay_root, "check")
    assert bounded.blocking_count == 205
    assert len(bounded.files) == 1
    assert bounded.truncated
