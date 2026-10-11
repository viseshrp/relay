"""Midstream launch preconditions and evidence preservation before workspace recovery."""

from __future__ import annotations

from dataclasses import replace
from functools import partial
from hashlib import sha256
import os
from pathlib import Path
import shutil
import subprocess

import pytest

from relay.errors import (
    ArtifactPreservationError,
    DirtyRepositoryError,
    WorkflowValidationError,
    WorktreeError,
)
from relay.execution.recovery import prepare_recovery_workspace
from relay.execution.resume import RecoveryTarget, resume_interrupted
from relay.execution.scheduler import dispatch_ready_nodes
from relay.projects.service import initialize_project, register_current_project
from relay.vcs.cleanliness import status_porcelain
from relay.vcs.commits import current_head
from relay.web.models import Artifact, NodeAttempt, NodeRun, Run, RunSnapshot
from relay.web.repositories import DjangoExecutionStore, DjangoProjectStore, DjangoReadStore
from tests.support import InlineEngine, RelayProject, git, init_repository, run_status


@pytest.fixture
def uncommitted_initial_project(tmp_path: Path) -> RelayProject:
    repository = init_repository(tmp_path / "new-project")
    initialized = initialize_project(repository)
    record = register_current_project(DjangoProjectStore(), repository)
    return RelayProject(repository, initialized.relay_root, record.id)


@pytest.mark.parametrize("line_ending", [b"\n", b"\r\n"])
def test_first_launch_preserves_untracked_untouched_initial_files(
    uncommitted_initial_project: RelayProject, engine: InlineEngine, line_ending: bytes
) -> None:
    project = uncommitted_initial_project
    starter = project.relay_root / "workflows/workflow.yaml"
    starter.write_bytes(starter.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", line_ending))
    workflow = project.write(
        ".relay/workflows/first.yaml",
        "version: 1\nname: First run\nnodes:\n  check: {type: command, run: [git, status]}\n",
    )
    initial = {
        path: path.read_bytes()
        for path in (
            project.relay_root / "prompts/prompt.md",
            project.relay_root / "workflows/workflow.yaml",
        )
    }

    run_id = engine.launch(project, "first")
    engine.drain(run_id)

    assert run_status(run_id) == "succeeded"
    assert workflow.exists()
    assert all(path.read_bytes() == content for path, content in initial.items())
    assert git(project.repository, "diff", "--cached", "--name-only") == ""
    assert len(status_porcelain(project.repository)) == 3


@pytest.mark.parametrize("relative", ["prompts/prompt.md", "workflows/workflow.yaml"])
def test_unused_initial_files_with_owner_edits_still_block_first_launch(
    uncommitted_initial_project: RelayProject, engine: InlineEngine, relative: str
) -> None:
    project = uncommitted_initial_project
    project.write(".relay/" + relative, "Owner's uncommitted content\n")
    project.write(
        ".relay/workflows/first.yaml",
        "version: 1\nname: First run\nnodes:\n  check: {type: command, run: [git, status]}\n",
    )

    with pytest.raises(DirtyRepositoryError):
        engine.launch(project, "first")

    assert not Run.objects.exists()


def test_staged_initial_files_still_block_first_launch(
    uncommitted_initial_project: RelayProject, engine: InlineEngine
) -> None:
    project = uncommitted_initial_project
    project.write(
        ".relay/workflows/first.yaml",
        "version: 1\nname: First run\nnodes:\n  check: {type: command, run: [git, status]}\n",
    )
    git(project.repository, "add", ".relay/prompts/prompt.md")

    with pytest.raises(DirtyRepositoryError):
        engine.launch(project, "first")

    assert not Run.objects.exists()


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_launch_preserves_owner_reports_and_snapshots_an_uncommitted_workflow(
    project: RelayProject,
    engine: InlineEngine,
    newline: str,
) -> None:
    from relay.web.models import RunSnapshot

    report = project.repository / "REVIEW.md"
    report.write_text("Owner's review\n", encoding="utf-8")
    workflow = project.relay_root / "workflows" / "new.yaml"
    text = "version: 1\nname: New\nnodes:\n  check: {type: command, run: [git, status]}\n"
    raw = text.replace("\n", newline).encode("utf-8")
    workflow.write_bytes(raw)
    run_id = engine.launch(project, "new")
    engine.drain(run_id)
    assert RunSnapshot.objects.get(run_id=run_id).workflow_yaml.encode("utf-8") == raw
    assert report.read_text(encoding="utf-8") == "Owner's review\n"
    assert set(status_porcelain(project.repository)) == {
        "?? REVIEW.md",
        "?? .relay/workflows/new.yaml",
    }


def test_launch_still_rejects_uncommitted_code_beside_owner_reports(
    project: RelayProject,
    engine: InlineEngine,
) -> None:
    (project.repository / "REVIEW.md").write_text("Review\n", encoding="utf-8")
    (project.repository / "code.py").write_text("unfinished\n", encoding="utf-8")
    with pytest.raises(DirtyRepositoryError):
        engine.launch(project, "workflow")
    assert not Run.objects.exists()


ENTRY_WORKFLOW = """version: 1
name: Midstream
inputs:
  target: {type: string}
entrypoints:
  - scope_path: root.implement
    inputs: [target]
nodes:
  prepare: {type: command, run: [git, status]}
  implement: {type: command, needs: [prepare], run: [git, status]}
"""


@pytest.mark.parametrize("requested", ["implement", "root.implement"])
def test_midstream_launch_normalizes_the_declared_scope_and_skips_preceding_work(
    project: RelayProject, engine: InlineEngine, requested: str
) -> None:
    project.write_workflow("entry", ENTRY_WORKFLOW)
    run_id = engine.launch(project, "entry", inputs={"target": "report"}, entry_point=requested)
    engine.drain(run_id)
    run = Run.objects.get(pk=run_id)
    assert (run.entry_point, run.status) == ("root.implement", "succeeded")
    assert NodeRun.objects.get(run_id=run_id, node_id="prepare").status == "skipped"


@pytest.mark.parametrize("requested", ["prepare", "unknown"])
def test_an_undeclared_midstream_launch_creates_no_run(
    project: RelayProject, engine: InlineEngine, requested: str
) -> None:
    project.write_workflow("entry", ENTRY_WORKFLOW)
    with pytest.raises(WorkflowValidationError):
        engine.launch(project, "entry", inputs={"target": "report"}, entry_point=requested)
    assert not Run.objects.exists()


def test_midstream_launch_requires_the_entrypoints_inputs(
    project: RelayProject, engine: InlineEngine
) -> None:
    project.write_workflow("entry", ENTRY_WORKFLOW)
    with pytest.raises(WorkflowValidationError):
        engine.launch(project, "entry", entry_point="implement")
    assert not Run.objects.exists()


@pytest.mark.parametrize("evidence", ["valid", "missing", "changed"])
def test_midstream_launch_requires_exact_artifact_evidence(
    project: RelayProject, engine: InlineEngine, evidence: str
) -> None:
    digest = sha256(b"approved").hexdigest()
    project.write("approved.txt", "changed" if evidence == "changed" else "approved")
    if evidence == "missing":
        (project.repository / "approved.txt").unlink()
    workflow = ENTRY_WORKFLOW.replace(
        "    inputs: [target]\n",
        f"    inputs: [target]\n    artifacts:\n"
        f"      approval: {{path: approved.txt, sha256: {digest}}}\n",
    )
    project.write_workflow("entry", workflow)
    if evidence == "valid":
        run_id = engine.launch(
            project, "entry", inputs={"target": "report"}, entry_point="implement"
        )
        assert Run.objects.get(pk=run_id).entry_point == "root.implement"
    else:
        with pytest.raises(ArtifactPreservationError):
            engine.launch(project, "entry", inputs={"target": "report"}, entry_point="implement")
        assert not Run.objects.exists()


@pytest.mark.parametrize(
    "scope",
    [
        "root.unknown",
        "root.after#1",
        "root.after.child",
        "root.repeat.child",
        "root.repeat#3.child",
    ],
)
def test_declared_entrypoints_cannot_name_impossible_node_scopes(
    project: RelayProject, engine: InlineEngine, scope: str
) -> None:
    project.write_workflow(
        "scope",
        "version: 1\nname: Scopes\nentrypoints:\n"
        f"  - scope_path: {scope}\nnodes:\n"
        "  repeat:\n    type: loop\n    max_iterations: 2\n    exhausted: after\n"
        '    until: "${{ loop.index >= 1 }}"\n    body:\n'
        "      child: {type: command, run: [git, status]}\n"
        "  after: {type: command, run: [git, status]}\n",
    )
    with pytest.raises(WorkflowValidationError):
        engine.launch(project, "scope", entry_point=scope)
    assert not Run.objects.exists()


def test_a_failed_git_worktree_creation_leaves_a_failed_launch_record(
    project: RelayProject, engine: InlineEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    project.write_workflow(
        "one", "version: 1\nname: One\nnodes:\n  a: {type: command, run: [git, status]}\n"
    )
    run = subprocess.run

    def failed_worktree(
        arguments: list[str], **options: object
    ) -> subprocess.CompletedProcess[str] | subprocess.CompletedProcess[bytes]:
        if "worktree" in arguments and "add" in arguments:
            return subprocess.CompletedProcess(
                arguments, 128, stdout="", stderr="worktree unavailable"
            )
        return run(arguments, **options)

    monkeypatch.setattr(subprocess, "run", failed_worktree)
    with pytest.raises(WorktreeError):
        engine.launch(project, "one")
    recorded = Run.objects.get()
    assert (recorded.status, recorded.failure_code) == ("failed", "worktree_error")


@pytest.fixture
def interrupted_writer(project: RelayProject, engine: InlineEngine) -> RecoveryTarget:
    project.write_workflow(
        "writer",
        "version: 1\nname: Writer\nnodes:\n"
        "  write: {type: command, writes: true, allow_no_commit: true, run: [git, status]}\n",
    )
    engine.launch(project, "writer")
    store = engine.store
    claim = store.claim_dispatch(engine.tokens.popleft(), "interrupted-worker")
    assert claim.attempt is not None
    (Path(claim.attempt.primary_worktree) / "unfinished.txt").write_text(
        "unfinished report", encoding="utf-8"
    )
    instance = store.acquire_instance(os.getpid(), "test-host")
    store.request_orderly_shutdown(instance)
    store.interrupt_active_attempts()
    store.release_instance(instance)
    return store.interrupted_targets()[0]


def test_writer_recovery_preserves_unfinished_bytes_before_restoring_the_checkout(
    interrupted_writer: RecoveryTarget,
) -> None:
    store = DjangoExecutionStore()
    prepare_recovery_workspace(store, interrupted_writer)
    artifact = Artifact.objects.get(declared_name="unfinished.txt")
    path, _name, _mime = DjangoReadStore().artifact_file(str(artifact.pk))
    assert path.read_bytes() == b"unfinished report"
    assert status_porcelain(Path(interrupted_writer.worktree_path)) == ()
    assert current_head(Path(interrupted_writer.worktree_path)) == interrupted_writer.starting_head


def test_repeating_workspace_recovery_keeps_the_original_evidence(
    interrupted_writer: RecoveryTarget,
) -> None:
    store = DjangoExecutionStore()
    prepare_recovery_workspace(store, interrupted_writer)
    ids = list(Artifact.objects.values_list("id", flat=True))
    prepare_recovery_workspace(store, interrupted_writer)
    assert list(Artifact.objects.values_list("id", flat=True)) == ids


def test_a_missing_primary_worktree_cannot_be_silently_recovered(
    interrupted_writer: RecoveryTarget,
) -> None:
    shutil.rmtree(interrupted_writer.worktree_path)
    with pytest.raises(WorktreeError):
        prepare_recovery_workspace(DjangoExecutionStore(), interrupted_writer)


def test_a_missing_ephemeral_reader_needs_no_workspace_repair(
    interrupted_writer: RecoveryTarget,
) -> None:
    shutil.rmtree(interrupted_writer.worktree_path)
    prepare_recovery_workspace(
        DjangoExecutionStore(), replace(interrupted_writer, ephemeral_reader=True)
    )
    assert not Artifact.objects.exists()


@pytest.fixture
def interrupted_paused_loop(project: RelayProject, engine: InlineEngine) -> RecoveryTarget:
    project.write_workflow(
        "loop",
        "version: 1\nname: Paused loop\nnodes:\n"
        "  repeat:\n    type: loop\n    max_iterations: 1\n    exhausted: stop\n"
        '    until: "${{ loop.index >= 1 }}"\n'
        "    body:\n      wait: {type: human_wait, prompt: Continue}\n"
        "      check: {type: command, needs: [wait], run: [git, status]}\n"
        "  stop: {type: command, run: [git, status]}\n",
    )
    run_id = engine.launch(project, "loop")
    engine.run_token(engine.tokens.popleft())
    store = engine.store
    store.configure_dispatch_pause(run_id, True, "pause-loop")
    assert NodeRun.objects.get(run_id=run_id, scope_path="root.repeat").status == "waiting"
    instance = store.acquire_instance(os.getpid(), "test-host")
    store.request_orderly_shutdown(instance)
    store.interrupt_active_attempts()
    store.release_instance(instance)
    target = next(
        target for target in store.interrupted_targets() if target.scope_path == "root.repeat"
    )
    (Path(target.worktree_path) / "REVIEW.md").write_bytes(b"Ready: No\n")
    return target


def test_paused_loop_restart_keeps_reports_snapshots_and_unstarted_children(
    interrupted_paused_loop: RecoveryTarget, engine: InlineEngine
) -> None:
    target = interrupted_paused_loop
    report = Path(target.worktree_path) / "REVIEW.md"
    snapshot = RunSnapshot.objects.get(run_id=target.run_id)
    frozen = (snapshot.workflow_yaml, snapshot.resolved_prompts, snapshot.hashes)
    attempt_ids = list(NodeAttempt.objects.values_list("id", flat=True))

    resumed = resume_interrupted(engine.store, partial(prepare_recovery_workspace, engine.store))
    dispatch_ready_nodes(engine.store, target.run_id, engine.tokens.append)
    engine.drain(target.run_id)

    assert resumed == (target.run_id,)
    run = Run.objects.get(pk=target.run_id)
    assert run.status == "running" and run.dispatch_paused is True
    assert run.recorded_head == target.protected_head
    assert report.read_bytes() == b"Ready: No\n"
    snapshot.refresh_from_db()
    assert (snapshot.workflow_yaml, snapshot.resolved_prompts, snapshot.hashes) == frozen
    assert list(NodeAttempt.objects.values_list("id", flat=True)) == attempt_ids
    assert not NodeAttempt.objects.filter(node_run__scope_path="root.repeat#1.check").exists()


@pytest.mark.parametrize(
    "change", ["untracked_code", "modified_code", "staged_report", "nested_report", "moved_head"]
)
def test_loop_restart_still_rejects_code_staged_reports_and_head_movement(
    interrupted_paused_loop: RecoveryTarget, change: str
) -> None:
    target = interrupted_paused_loop
    worktree = Path(target.worktree_path)
    if change == "untracked_code":
        (worktree / "unfinished.py").write_bytes(b"unfinished\n")
    elif change == "modified_code":
        (worktree / "README.md").write_bytes(b"unfinished\n")
    elif change == "staged_report":
        git(worktree, "add", "REVIEW.md")
    elif change == "nested_report":
        (worktree / "nested").mkdir()
        (worktree / "nested/REVIEW.md").write_bytes(b"Ready: No\n")
    else:
        git(worktree, "commit", "--allow-empty", "-q", "-m", "Unrecorded head")

    expected = WorktreeError if change == "moved_head" else DirtyRepositoryError
    with pytest.raises(expected):
        prepare_recovery_workspace(DjangoExecutionStore(), target)

    assert run_status(target.run_id) == "interrupted"
    assert (worktree / "REVIEW.md").read_bytes() == b"Ready: No\n"
