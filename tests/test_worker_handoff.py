"""A stalled writer keeps its workspace until its owning process cannot mutate it."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path
import subprocess
import sys
import threading

from django.db import connections
import pytest

from relay.errors import PersistenceError
from relay.execution.cancellation import owned_process_argv, signal_process_tree
from relay.execution.dispatch import ClaimDisposition
from relay.execution.process_identity import process_identity
from relay.execution.reconcile import reconcile_once
from relay.execution.runner import ExecutionOutcome, OutcomeKind
from relay.vcs.commits import CommitResult
from relay.web import supervisor
from relay.web.models import ActionsJobLease, NodeAttempt
from tests.support import Clock, InlineEngine, RelayProject, git
from tests.test_supervisor_recovery import stdout_line


@pytest.mark.parametrize("jump", [3600, -3600, 7 * 86400])
def test_clock_jump_or_sleep_cannot_hand_off_a_writer_before_git_finalization(
    project: RelayProject,
    tmp_path: Path,
    clock: Clock,
    monkeypatch: pytest.MonkeyPatch,
    jump: int,
) -> None:
    from relay.execution import runner

    project.write_workflow(
        "owned",
        (
            "name: Owned\n"
            "jobs:\n"
            "  old:\n"
            "    steps:\n"
            "    - id: work\n"
            "      uses: relay/command@v1\n"
            "      with:\n"
            '        argv: \'["git", "status"]\'\n'
            "  replacement:\n"
            "    steps:\n"
            "    - id: work\n"
            "      uses: relay/command@v1\n"
            "      with:\n"
            '        argv: \'["git", "status"]\'\n'
        ),
    )
    reached_git = threading.Event()
    allow_git = threading.Event()
    original = runner.accept_job_result

    def pause_finalization(
        worktree: Path,
        starting_head: str,
        job_id: str,
        *,
        snapshot_files: frozenset[str] = frozenset(),
    ) -> CommitResult:
        reached_git.set()
        assert allow_git.wait(10)
        return original(worktree, starting_head, job_id, snapshot_files=snapshot_files)

    monkeypatch.setattr(runner, "accept_job_result", pause_finalization)

    class Writer:
        def execute(self, context: runner.AttemptContext) -> ExecutionOutcome:
            (context.worktree / "owned.txt").write_text("old worker bytes\n", encoding="utf-8")
            git(context.worktree, "add", "owned.txt")
            git(context.worktree, "commit", "-qm", "Owned bytes")
            return ExecutionOutcome(OutcomeKind.SUCCEEDED)

    engine = InlineEngine({"actions_job": Writer()}, tmp_path / "artifacts")
    run_id = engine.launch(project, "owned")
    old, replacement = engine.tokens.popleft(), engine.tokens.popleft()

    def run() -> None:
        try:
            engine.run_token(old)
        finally:
            connections.close_all()

    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(run)
        try:
            assert reached_git.wait(10)
            clock.advance(jump)
            reconcile_once(engine.store, lambda _: None, orderly_shutdown=False)
            assert ActionsJobLease.objects.filter(node__run_id=run_id).exists()
            result = engine.store.claim_dispatch(replacement, "replacement-worker")
            assert result.disposition is ClaimDisposition.BUSY
            assert NodeAttempt.objects.get(worker_id=engine.worker_id).status == "running"
        finally:
            allow_git.set()
            future.result(timeout=10)


def test_owned_attempt_tree_is_gone_before_the_supervisor_can_recover(tmp_path: Path) -> None:
    child_code = "import time; time.sleep(60)"
    parent_code = (
        "import subprocess, sys; "
        f"child = subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        "print(child.pid, flush=True); sys.stdin.buffer.read()"
    )
    arguments = owned_process_argv((sys.executable, "-u", "-c", parent_code))
    with subprocess.Popen(  # noqa: S603
        arguments,
        cwd=tmp_path,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) if os.name == "nt" else 0,
        start_new_session=os.name != "nt",
    ) as worker:
        descendant = int(stdout_line(worker, 10))
        identity = process_identity(worker.pid)
        assert identity is not None
        try:
            supervisor._force_attempt_processes((("attempt", identity),))
            worker.wait(timeout=10)
            assert process_identity(worker.pid) is None
            assert process_identity(descendant) is None
        finally:
            if worker.poll() is None:
                signal_process_tree(worker.pid, force=True)


@pytest.mark.skipif(os.name == "nt", reason="Windows Job Object kills children on launcher exit")
def test_unverified_surviving_child_blocks_recovery_after_its_leader_exits(tmp_path: Path) -> None:
    child_code = "import time; time.sleep(60)"
    parent_code = (
        "import subprocess, sys; "
        f"child = subprocess.Popen([sys.executable, '-c', {child_code!r}]); "
        "print(child.pid, flush=True); sys.stdin.buffer.read()"
    )
    with subprocess.Popen(  # noqa: S603
        [sys.executable, "-u", "-c", parent_code],
        cwd=tmp_path,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        text=True,
        start_new_session=True,
    ) as worker:
        descendant = int(stdout_line(worker, 10))
        identity = process_identity(worker.pid)
        assert identity is not None and worker.stdin is not None
        try:
            worker.stdin.close()
            worker.wait(timeout=10)
            with pytest.raises(PersistenceError, match="unverified children"):
                supervisor._force_attempt_processes((("attempt", identity),))
            assert process_identity(descendant) is not None
        finally:
            signal_process_tree(worker.pid, force=True)
