"""Opt-in run integration, strict target cleanliness, and crash recovery."""

from __future__ import annotations

import json
from pathlib import Path

from django.db import DatabaseError
import pytest

from relay.errors import DirtyRepositoryError, RunMergeError
from relay.execution.reconcile import reconcile_once
from relay.execution.resume import recovery_workspace_lock
from relay.vcs.artifacts import retained_attempt_ref
from relay.vcs.git import git_stdout
from relay.web.models import Artifact, NodeAttempt, NodeRun, Run, RunEvent
from relay.web.repositories import DjangoExecutionStore
from tests.support import PYTHON, InlineEngine, RelayProject, event_types, git


def writer_workflow(project: RelayProject) -> None:
    scripts = []
    for name in ("first.txt", "second.txt"):
        scripts.append(
            "from pathlib import Path; import subprocess; "
            f"Path('{name}').write_text('run result'); "
            f"subprocess.run(['git', 'add', '{name}'], check=True); "
            f"subprocess.run(['git', 'commit', '-q', '-m', '{name}'], check=True)"
        )
    project.write_workflow(
        "writer",
        json.dumps(
            {
                "version": 1,
                "name": "Merge result",
                "nodes": {
                    "first": {"type": "command", "writes": True, "run": [PYTHON, "-c", scripts[0]]},
                    "second": {
                        "type": "command",
                        "writes": True,
                        "needs": ["first"],
                        "run": [PYTHON, "-c", scripts[1]],
                    },
                    "review": {
                        "type": "command",
                        "needs": ["second"],
                        "run": ["git", "status", "--short"],
                    },
                },
            }
        ),
    )


def test_merge_all_writer_commits_then_remove_every_run_worktree(
    project: RelayProject,
    engine: InlineEngine,
) -> None:
    writer_workflow(project)
    run_id = engine.launch(project, "writer", cleanup_policy="merge_on_success")
    engine.drain(run_id)
    run = Run.objects.get(pk=run_id)
    assert (run.status, run.worktree_state) == ("succeeded", "removed")
    assert run.merged_commit == run.recorded_head == git(project.repository, "rev-parse", "HEAD")
    assert git(project.repository, "symbolic-ref", "--short", "HEAD") == "main"
    assert git(project.repository, "status", "--porcelain") == ""
    for name in ("first.txt", "second.txt"):
        assert (project.repository / name).read_text() == "run result"
    assert not Path(run.worktree_path).exists()
    assert git(project.repository, "worktree", "list", "--porcelain").count("worktree ") == 1
    assert git(project.repository, "rev-parse", run.run_branch) == run.recorded_head
    for attempt in NodeAttempt.objects.filter(node_run__run_id=run_id):
        assert git(project.repository, "rev-parse", retained_attempt_ref(run_id, str(attempt.pk)))
    kinds = event_types(run_id, "run.")
    assert kinds[-4:] == ["run.completing", "run.merged", "run.cleanup_succeeded", "run.succeeded"]
    from relay.execution.completion import complete_run_merge

    complete_run_merge(engine.store, run_id)
    engine.store.resume_run_completions()
    assert event_types(run_id, "run.") == kinds


@pytest.mark.parametrize("policy", ["retain", "clean_on_success"])
def test_existing_completion_policies_never_merge(
    project: RelayProject,
    engine: InlineEngine,
    policy: str,
) -> None:
    writer_workflow(project)
    original = git(project.repository, "rev-parse", "HEAD")
    run_id = engine.launch(project, "writer", cleanup_policy=policy)
    engine.drain(run_id)
    run = Run.objects.get(pk=run_id)
    assert run.status == "succeeded"
    assert run.merged_commit is None
    assert git(project.repository, "rev-parse", "HEAD") == original
    assert Path(run.worktree_path).exists() == (policy == "retain")


@pytest.mark.parametrize("change", ["tracked", "staged", "untracked", "report", "workflow"])
def test_dirty_target_fails_and_preserves_every_owner_byte_and_run_commit(
    project: RelayProject,
    engine: InlineEngine,
    change: str,
) -> None:
    writer_workflow(project)
    original = git(project.repository, "rev-parse", "HEAD")
    run_id = engine.launch(project, "writer", cleanup_policy="merge_on_success")
    path = (
        "REVIEW.md"
        if change == "report"
        else ".relay/workflows/writer.yaml"
        if change == "workflow"
        else "owner.txt"
        if change == "untracked"
        else "README.md"
    )
    changed = project.write(path, "owner changes\n")
    if change == "staged":
        git(project.repository, "add", path)
    status = git(project.repository, "status", "--porcelain")
    engine.drain(run_id)
    run = Run.objects.get(pk=run_id)
    assert (run.status, run.failure_code, run.worktree_state) == (
        "failed",
        "dirty_repository_error",
        "created",
    )
    assert changed.read_text() == "owner changes\n"
    assert git(project.repository, "status", "--porcelain") == status
    assert git(project.repository, "rev-parse", "HEAD") == original
    assert run.merged_commit is None
    assert Path(run.worktree_path).is_dir()
    assert git(project.repository, "rev-parse", run.run_branch) == run.recorded_head != original
    assert Artifact.objects.filter(attempt__node_run__run_id=run_id).exists()
    assert set(NodeRun.objects.filter(run_id=run_id).values_list("status", flat=True)) == {
        "succeeded"
    }
    assert (
        RunEvent.objects.get(run_id=run_id, type="error").payload["code"]
        == "dirty_repository_error"
    )


@pytest.mark.parametrize("relative", ["REVIEW.md", ".relay/workflows/writer.yaml"])
def test_merge_launch_rejects_the_usual_unstaged_report_and_workflow_exemptions(
    project: RelayProject,
    engine: InlineEngine,
    relative: str,
) -> None:
    writer_workflow(project)
    if relative.endswith("yaml"):
        path = project.repository / relative
        path.write_text(path.read_text() + "\n")
    else:
        project.write(relative, "Owner review\n")
    with pytest.raises(DirtyRepositoryError):
        engine.launch(project, "writer", cleanup_policy="merge_on_success")
    assert not Run.objects.exists()


@pytest.mark.parametrize("change", ["switched", "detached", "diverged", "operation"])
def test_target_branch_changes_fail_without_switching_resetting_or_conflicts(
    project: RelayProject,
    engine: InlineEngine,
    change: str,
) -> None:
    writer_workflow(project)
    run_id = engine.launch(project, "writer", cleanup_policy="merge_on_success")
    if change == "switched":
        git(project.repository, "checkout", "-b", "owner-work")
    elif change == "detached":
        git(project.repository, "checkout", "--detach")
    elif change == "diverged":
        project.write("owner.txt", "committed owner work")
        project.commit("Advance active branch")
    else:
        marker = Path(git_stdout(project.repository, ["rev-parse", "--git-path", "MERGE_HEAD"]))
        (project.repository / marker).write_text(git(project.repository, "rev-parse", "HEAD"))
    before = git(project.repository, "rev-parse", "HEAD")
    engine.drain(run_id)
    run = Run.objects.get(pk=run_id)
    assert (run.status, run.failure_code) == ("failed", "run_merge_failed")
    assert run.merged_commit is None
    assert git(project.repository, "rev-parse", "HEAD") == before
    assert git(project.repository, "status", "--porcelain") == ""
    assert Path(run.worktree_path).exists()


def test_detached_launch_cannot_request_a_merge(
    project: RelayProject, engine: InlineEngine
) -> None:
    writer_workflow(project)
    git(project.repository, "checkout", "--detach")
    with pytest.raises(RunMergeError):
        engine.launch(project, "writer", cleanup_policy="merge_on_success")
    assert not Run.objects.exists()


def test_failed_job_does_not_merge_or_delete_the_workspace(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow(
        "failure",
        "version: 1\nname: Failure\nnodes:\n"
        f'  fail: {{type: command, run: ["{PYTHON}", -c, "raise SystemExit(2)"]}}\n',
    )
    head = git(project.repository, "rev-parse", "HEAD")
    run_id = engine.launch(project, "failure", cleanup_policy="merge_on_success")
    engine.drain(run_id)
    run = Run.objects.get(pk=run_id)
    assert run.status == "failed"
    assert run.merged_commit is None
    assert Path(run.worktree_path).exists()
    assert git(project.repository, "rev-parse", "HEAD") == head


@pytest.mark.parametrize("point", ["record", "remove", "finish"])
def test_restart_resumes_completion_without_repeating_the_merge_or_losing_evidence(
    project: RelayProject,
    engine: InlineEngine,
    monkeypatch: pytest.MonkeyPatch,
    point: str,
) -> None:
    from relay.execution import completion

    writer_workflow(project)
    run_id = engine.launch(project, "writer", cleanup_policy="merge_on_success")

    def crashed(*args: object, **kwargs: object) -> None:
        message = "Process lost before persistence"
        raise DatabaseError(message)

    with monkeypatch.context() as patch:
        if point == "record":
            patch.setattr(DjangoExecutionStore, "record_run_merge", crashed)
        elif point == "remove":
            patch.setattr(completion, "remove_worktree", crashed)
        else:
            patch.setattr(DjangoExecutionStore, "finish_run_completion", crashed)
        engine.drain(run_id)
    assert Run.objects.get(pk=run_id).status == "completing"
    head = git(project.repository, "rev-parse", "HEAD")
    reconcile_once(engine.store, engine.tokens.append, orderly_shutdown=False)
    engine.store.resume_run_completions()
    run = Run.objects.get(pk=run_id)
    assert (run.status, run.worktree_state) == ("succeeded", "removed")
    assert run.merged_commit == head == git(project.repository, "rev-parse", "HEAD")
    assert RunEvent.objects.filter(run_id=run_id, type="run.merged").count() == 1
    assert not Path(run.worktree_path).exists()


def test_busy_completion_waits_for_the_workspace_lock(
    project: RelayProject, engine: InlineEngine
) -> None:
    writer_workflow(project)
    run_id = engine.launch(project, "writer", cleanup_policy="merge_on_success")
    head = git(project.repository, "rev-parse", "HEAD")
    with recovery_workspace_lock(run_id):
        engine.drain(run_id)
        assert Run.objects.get(pk=run_id).status == "completing"
        assert git(project.repository, "rev-parse", "HEAD") == head
        assert engine.store.request_run_cancellation(run_id, "late-cancel").value == "stale"
    engine.store.resume_run_completions()
    assert Run.objects.get(pk=run_id).status == "succeeded"


@pytest.mark.parametrize("damage", ["record", "bytes", "worktree", "branch"])
def test_unpreserved_or_changed_evidence_and_workspaces_block_integration(
    project: RelayProject,
    engine: InlineEngine,
    damage: str,
) -> None:
    from relay.paths import artifacts_dir

    writer_workflow(project)
    run_id = engine.launch(project, "writer", cleanup_policy="merge_on_success")
    head = git(project.repository, "rev-parse", "HEAD")
    with recovery_workspace_lock(run_id):
        engine.drain(run_id)
    run = Run.objects.get(pk=run_id)
    if damage == "record":
        Artifact.objects.filter(attempt__node_run__run_id=run_id).update(
            preservation_state="pending"
        )
    elif damage == "bytes":
        attempt = NodeAttempt.objects.filter(node_run__run_id=run_id).first()
        assert attempt is not None
        (artifacts_dir() / run_id / str(attempt.pk) / "manifest.json").write_text("{}")
    elif damage == "worktree":
        (Path(run.worktree_path) / "unexpected.txt").write_text("keep these bytes")
    else:
        git(Path(run.worktree_path), "commit", "--allow-empty", "-m", "Unrecorded work")
    engine.store.resume_run_completions()
    assert Run.objects.get(pk=run_id).status == "failed"
    assert git(project.repository, "rev-parse", "HEAD") == head
    assert Path(run.worktree_path).exists()


def test_removal_failure_reports_failure_after_recording_the_completed_merge(
    project: RelayProject,
    engine: InlineEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.test_engine_failures import refuse_removal

    writer_workflow(project)
    run_id = engine.launch(project, "writer", cleanup_policy="merge_on_success")
    checkout = Path(Run.objects.get(pk=run_id).worktree_path)
    refuse_removal(checkout, monkeypatch)
    engine.drain(run_id)
    run = Run.objects.get(pk=run_id)
    assert (run.status, run.failure_code) == ("failed", "worktree_error")
    assert run.merged_commit == git(project.repository, "rev-parse", "HEAD")
    assert checkout.exists()


def test_git_merge_failure_is_publicly_sanitized_and_keeps_the_target_clean(
    project: RelayProject,
    engine: InlineEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from relay.vcs import merge
    from relay.vcs.git import GitResult

    writer_workflow(project)
    run_id = engine.launch(project, "writer", cleanup_policy="merge_on_success")
    original = merge.run_git

    def failed_git(repository: Path, arguments: list[str], *, check: bool = True) -> GitResult:
        if "merge" in arguments:
            return GitResult("", "private third-party details", 128)
        return original(repository, arguments, check=check)

    monkeypatch.setattr(merge, "run_git", failed_git)
    head = git(project.repository, "rev-parse", "HEAD")
    engine.drain(run_id)
    run = Run.objects.get(pk=run_id)
    assert run.status == "failed"
    assert "private third-party details" not in json.dumps(
        list(RunEvent.objects.filter(run_id=run_id).values_list("payload", flat=True))
    )
    assert git(project.repository, "rev-parse", "HEAD") == head
    assert git(project.repository, "status", "--porcelain") == ""
    assert Path(run.worktree_path).exists()


def test_missing_primary_worktree_before_merge_fails_without_advancing_the_target(
    project: RelayProject, engine: InlineEngine
) -> None:
    from relay.vcs.worktree import remove_worktree

    writer_workflow(project)
    run_id = engine.launch(project, "writer", cleanup_policy="merge_on_success")
    head = git(project.repository, "rev-parse", "HEAD")
    with recovery_workspace_lock(run_id):
        engine.drain(run_id)
    run = Run.objects.get(pk=run_id)
    remove_worktree(project.repository, Path(run.worktree_path))
    engine.store.resume_run_completions()
    run.refresh_from_db()
    assert (run.status, run.failure_code) == ("failed", "run_merge_failed")
    assert run.merged_commit is None
    assert git(project.repository, "rev-parse", "HEAD") == head
    assert git(project.repository, "rev-parse", run.run_branch) == run.recorded_head


def test_cleanup_stops_if_the_owner_undoes_a_merge_before_restart(
    project: RelayProject,
    engine: InlineEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from relay.execution import completion

    writer_workflow(project)
    head = git(project.repository, "rev-parse", "HEAD")
    run_id = engine.launch(project, "writer", cleanup_policy="merge_on_success")

    def crashed(repository: Path, worktree: Path) -> None:
        message = "Process lost before worktree removal"
        raise DatabaseError(message)

    with monkeypatch.context() as patch:
        patch.setattr(completion, "remove_worktree", crashed)
        engine.drain(run_id)
    run = Run.objects.get(pk=run_id)
    assert run.status == "completing"
    assert run.merged_commit is not None
    git(project.repository, "reset", "--hard", head)
    engine.store.resume_run_completions()
    run.refresh_from_db()
    assert (run.status, run.failure_code) == ("failed", "run_merge_failed")
    assert git(project.repository, "rev-parse", "HEAD") == head
    assert Path(run.worktree_path).exists()
    assert (Path(run.worktree_path) / "second.txt").read_text() == "run result"


@pytest.mark.parametrize("point", ["remove", "lock"])
def test_filesystem_failure_keeps_the_run_workspace_and_hides_private_details(
    project: RelayProject,
    engine: InlineEngine,
    monkeypatch: pytest.MonkeyPatch,
    point: str,
) -> None:
    from relay.execution import completion
    from relay.manage import MigrationLock

    writer_workflow(project)
    head = git(project.repository, "rev-parse", "HEAD")
    run_id = engine.launch(project, "writer", cleanup_policy="merge_on_success")

    def refused(repository: Path, worktree: Path) -> None:
        message = "private filesystem details"
        raise PermissionError(message)

    if point == "remove":
        monkeypatch.setattr(completion, "remove_worktree", refused)
    else:
        original = MigrationLock.__enter__

        def refused_lock(lock: MigrationLock) -> MigrationLock:
            if lock.purpose == "run merge":
                message = "private filesystem details"
                raise PermissionError(message)
            return original(lock)

        monkeypatch.setattr(MigrationLock, "__enter__", refused_lock)
    engine.drain(run_id)
    run = Run.objects.get(pk=run_id)
    assert (run.status, run.failure_code) == ("failed", "run_merge_failed")
    if point == "remove":
        assert run.merged_commit == git(project.repository, "rev-parse", "HEAD")
    else:
        assert run.merged_commit is None
        assert git(project.repository, "rev-parse", "HEAD") == head
    assert Path(run.worktree_path).exists()
    assert "private filesystem details" not in json.dumps(
        list(RunEvent.objects.filter(run_id=run_id).values_list("payload", flat=True))
    )


def test_a_changed_run_branch_ref_is_not_merged_even_when_the_worktree_head_is_valid(
    project: RelayProject, engine: InlineEngine
) -> None:
    writer_workflow(project)
    head = git(project.repository, "rev-parse", "HEAD")
    run_id = engine.launch(project, "writer", cleanup_policy="merge_on_success")
    with recovery_workspace_lock(run_id):
        engine.drain(run_id)
    run = Run.objects.get(pk=run_id)
    git(Path(run.worktree_path), "checkout", "--detach")
    git(project.repository, "branch", "--force", run.run_branch, head)
    engine.store.resume_run_completions()
    run.refresh_from_db()
    assert (run.status, run.failure_code) == ("failed", "run_merge_failed")
    assert run.merged_commit is None
    assert git(project.repository, "rev-parse", "HEAD") == head
    assert Path(run.worktree_path).exists()


def test_merge_success_is_verified_against_the_actual_target_head(
    project: RelayProject,
    engine: InlineEngine,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from relay.vcs import merge
    from relay.vcs.git import GitResult

    writer_workflow(project)
    head = git(project.repository, "rev-parse", "HEAD")
    run_id = engine.launch(project, "writer", cleanup_policy="merge_on_success")
    original = merge.run_git

    def unchanged_git(repository: Path, arguments: list[str], *, check: bool = True) -> GitResult:
        if "merge" in arguments:
            return GitResult("", "", 0)
        return original(repository, arguments, check=check)

    monkeypatch.setattr(merge, "run_git", unchanged_git)
    engine.drain(run_id)
    run = Run.objects.get(pk=run_id)
    assert (run.status, run.failure_code) == ("failed", "run_merge_failed")
    assert run.merged_commit is None
    assert git(project.repository, "rev-parse", "HEAD") == head
    assert Path(run.worktree_path).exists()
