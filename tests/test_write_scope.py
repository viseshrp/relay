"""Agent steps with allowed-paths fail when they change anything outside them."""

from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

import pytest

from relay.constants import DEFAULT_RECOVERY_PROMPT
from relay.errors import NodeExecutionError, OutputValidationError, WorkflowValidationError
from relay.execution.nodes import node_executors
from relay.execution.runner import AttemptContext, ExecutionOutcome, OutcomeKind
from relay.vcs.write_scope import (
    baseline_ref,
    capture_worktree,
    path_allowed,
    require_allowed_changes,
)
from relay.web.models import AutomaticRetry, NodeAttempt, NodeRun, Run
from relay.workflows.actions.builtins import parse_allowed_paths
from relay.workflows.schema import AgentNode
from tests.support import FakeAgents, InlineEngine, RelayProject, git, init_repository


@pytest.mark.parametrize(
    "path,pattern,allowed",
    [
        ("docs/guide.md", "docs/**", True),
        ("docs/a/b/c.md", "docs/**", True),
        ("docs/guide.md", "docs/", True),
        ("documents/guide.md", "docs/**", False),
        ("src/app.py", "src/*.py", True),
        ("src/nested/app.py", "src/*.py", False),
        ("src/nested/app.py", "src/**/*.py", True),
        ("src/app.py", "src/**/*.py", True),
        ("README.md", "README.md", True),
        ("readme.md", "README.md", False),
        ("a.txt", "?.txt", True),
        ("ab.txt", "?.txt", False),
        ("file[1].md", "file[1].md", True),
    ],
)
def test_patterns_match_exact_case_sensitive_paths(path: str, pattern: str, allowed: bool) -> None:
    assert path_allowed(path, (pattern,)) is allowed


@pytest.mark.parametrize(
    "value",
    [
        "/etc/passwd",
        "../outside",
        "docs/../src",
        "docs\\guide.md",
        "C:/work",
        "${{ inputs.paths }}",
        "",
        "\n".join(f"p{index}" for index in range(101)),
        ["docs/**"],
    ],
)
def test_allowed_paths_reject_unsafe_or_dynamic_patterns(value: object) -> None:
    with pytest.raises(WorkflowValidationError):
        parse_allowed_paths(value)


def test_allowed_paths_parse_one_pattern_per_line() -> None:
    assert parse_allowed_paths("docs/**\n\n  src/*.py  \n") == ("docs/**", "src/*.py")


def test_capture_leaves_head_index_and_files_unchanged(tmp_path: Path) -> None:
    repository = init_repository(tmp_path / "repository")
    (repository / "staged.txt").write_text("staged\n", encoding="utf-8")
    git(repository, "add", "staged.txt")
    (repository / "loose.txt").write_text("loose\n", encoding="utf-8")
    head = git(repository, "rev-parse", "HEAD")
    status = git(repository, "status", "--porcelain=v1")
    before = capture_worktree(repository)
    assert git(repository, "rev-parse", "HEAD") == head
    assert git(repository, "status", "--porcelain=v1") == status
    (repository / "loose.txt").write_text("changed\n", encoding="utf-8")
    (repository / "new.txt").write_text("new\n", encoding="utf-8")
    with pytest.raises(OutputValidationError) as raised:
        require_allowed_changes(repository, before, ("docs/**",))
    assert "loose.txt" in raised.value.message
    assert "new.txt" in raised.value.message
    assert "staged.txt" not in raised.value.message


@dataclass
class WritingDriver:
    """Write the requested files, recovering into scope when told to repair."""

    files: tuple[str, ...]
    repaired: tuple[str, ...] = ("docs/fixed.md",)
    calls: list[AttemptContext] = field(default_factory=list)

    def execute(self, context: AttemptContext, node: AgentNode) -> ExecutionOutcome:
        del node
        self.calls.append(context)
        recovering = any(
            DEFAULT_RECOVERY_PROMPT in text for text in context.attempt.prompt_contents
        )
        if recovering:
            for name in self.files:
                path = context.worktree / name
                if path.exists():
                    path.unlink()
        for name in self.repaired if recovering else self.files:
            path = context.worktree / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("written\n", encoding="utf-8")
        return ExecutionOutcome(OutcomeKind.SUCCEEDED)


def _run(
    project: RelayProject,
    driver: WritingDriver,
    *,
    allowed: str | None = "docs/**",
    recovery: bool = False,
) -> str:
    from relay.paths import artifacts_dir

    fake = {"agent": "codex", "model": "m1"}
    project.write_workflow(
        "scoped",
        json.dumps(
            {
                "recovery": {"enabled": recovery, "max_retries": 2},
                "jobs": {
                    "write": {
                        "steps": [
                            {
                                "id": "agent",
                                "uses": "relay/agent@v1",
                                "with": {
                                    **fake,
                                    **({"allowed-paths": allowed} if allowed else {}),
                                },
                            }
                        ]
                    }
                },
            }
        ),
    )
    engine = InlineEngine(node_executors(agent_driver=driver), artifacts_dir())
    run_id = engine.launch(project, "scoped")
    engine.drain(run_id)
    return run_id


def _step_attempts(run_id: str) -> list[NodeAttempt]:
    return list(
        NodeAttempt.objects.filter(
            node_run__run_id=run_id, node_run__scope_path="root.write.agent"
        ).order_by("attempt_number")
    )


def test_changes_inside_the_scope_and_root_reports_succeed(
    project: RelayProject, fake_agents: FakeAgents
) -> None:
    fake_agents.install("codex")
    run_id = _run(project, WritingDriver(("docs/guide.md", "docs/a/b.md", "REVIEW.md")))
    assert Run.objects.get(pk=run_id).status == "succeeded"


@pytest.mark.parametrize("name", ["src/app.py", "outside.txt"])
def test_out_of_scope_changes_fail_with_their_paths(
    project: RelayProject, fake_agents: FakeAgents, name: str
) -> None:
    fake_agents.install("codex")
    run_id = _run(project, WritingDriver(("docs/guide.md", name)))
    assert Run.objects.get(pk=run_id).status == "failed"
    (attempt,) = _step_attempts(run_id)
    assert attempt.error_code == "output_validation_error"
    assert attempt.stop_reason == "output_invalid"
    ended = attempt.events.get(type="attempt.ended")
    assert name in ended.payload["error_message"]
    assert "docs/guide.md" not in ended.payload["error_message"]


def test_steps_without_allowed_paths_keep_todays_behavior(
    project: RelayProject, fake_agents: FakeAgents
) -> None:
    fake_agents.install("codex")
    run_id = _run(project, WritingDriver(("src/app.py",)), allowed=None)
    assert Run.objects.get(pk=run_id).status == "succeeded"


def test_automatic_repair_receives_the_out_of_scope_paths(
    project: RelayProject, fake_agents: FakeAgents
) -> None:
    fake_agents.install("codex")
    driver = WritingDriver(("src/app.py",))
    run_id = _run(project, driver, recovery=True)
    assert len(driver.calls) == 2
    assert "src/app.py" in driver.calls[1].attempt.prompt_contents[-1]
    assert AutomaticRetry.objects.get(state="resumed")
    assert Run.objects.get(pk=run_id).status == "succeeded"


def test_scoped_step_baseline_is_kept_reachable_in_the_run_namespace(
    project: RelayProject, fake_agents: FakeAgents
) -> None:
    fake_agents.install("codex")
    run_id = _run(project, WritingDriver(("docs/guide.md",)))
    node = NodeRun.objects.get(run_id=run_id, scope_path="root.write.agent")
    assert len(node.write_baseline) == 40
    reference = baseline_ref(run_id, str(node.pk))
    assert reference.startswith(f"refs/relay/attempts/{run_id}/")
    assert git(project.repository, "rev-parse", f"{reference}^{{tree}}") == node.write_baseline


def test_a_missing_baseline_stops_the_check_instead_of_passing(tmp_path: Path) -> None:
    repository = init_repository(tmp_path / "repository")
    with pytest.raises(NodeExecutionError, match="starting snapshot"):
        require_allowed_changes(repository, "0" * 40, ("docs/**",))
