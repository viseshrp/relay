"""Named-product lifecycle, immutable caches, and failure paths in real storage."""

from datetime import timedelta
from pathlib import Path
from typing import Any

from django.db import IntegrityError
from django.utils import timezone
import pytest

from relay.errors import NodeExecutionError
from relay.execution.nodes import node_executors
from relay.execution.nodes.actions import ActionsStepExecutor
from relay.execution.runner import AttemptContext, ExecutionOutcome
from relay.web.actions_products import execute_product, expire_artifacts
from relay.web.models import ActionsArtifact, ActionsCache, RunEvent
from relay.workflows.schema import ActionsStepNode
from tests.support import InlineEngine, RelayProject


@pytest.fixture
def product_context(
    project: RelayProject, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[AttemptContext, ActionsStepNode]:
    captured: list[AttemptContext] = []
    original = ActionsStepExecutor.execute

    def record(self: ActionsStepExecutor, context: AttemptContext) -> ExecutionOutcome:
        captured.append(context)
        return original(self, context)

    monkeypatch.setattr(ActionsStepExecutor, "execute", record)
    project.write_workflow(
        "products",
        "jobs: {main: {runs-on: self-hosted, steps: "
        "[{uses: relay/human-wait@v1, with: {prompt: Continue?}}]}}",
    )
    engine = InlineEngine(node_executors(), tmp_path / "attempt-artifacts")
    run_id = engine.launch(project, "products")
    engine.drain(run_id)
    assert len(captured) == 1
    context = captured[0]
    assert context.attempt.run_id == run_id
    (context.worktree / "result.txt").write_bytes(b"original\n")
    return context, ActionsStepNode.model_validate(context.attempt.frozen_def)


@pytest.mark.parametrize(
    "inputs,reason",
    [
        ({"name": ""}, "names"),
        ({"name": "bad/name"}, "names"),
        ({"name": "x" * 257}, "names"),
        ({"retention-days": "1.5"}, "integer"),
        ({"retention-days": "366"}, "between"),
        ({"retention-days": "-1"}, "between"),
    ],
)
def test_invalid_artifact_contracts_leave_no_records(
    product_context: tuple[AttemptContext, ActionsStepNode], inputs: dict[str, str], reason: str
) -> None:
    context, node = product_context
    with pytest.raises(NodeExecutionError, match=reason):
        execute_product(
            context, "relay/upload-artifact@v1", {"path": "result.txt", **inputs}, {}, node
        )
    assert not ActionsArtifact.objects.exists()


def test_artifacts_are_immutable_downloadable_and_expire_only_verified_optional_bytes(
    product_context: tuple[AttemptContext, ActionsStepNode],
) -> None:
    context, node = product_context
    result = execute_product(
        context,
        "relay/upload-artifact@v1",
        {"path": "result.txt", "name": "result", "retention-days": "1"},
        {},
        node,
    )
    artifact = ActionsArtifact.objects.get()
    assert result.outputs["artifact-id"] == str(artifact.pk)
    assert result.outputs["artifact-digest"] == artifact.digest
    assert artifact.expires_at > timezone.now()
    directory = Path(artifact.directory)
    with pytest.raises(NodeExecutionError, match="immutable"):
        execute_product(
            context, "relay/upload-artifact@v1", {"path": "result.txt", "name": "result"}, {}, node
        )
    execute_product(
        context, "relay/download-artifact@v1", {"name": "result", "path": "restored"}, {}, node
    )
    assert (context.worktree / "restored/result.txt").read_bytes() == b"original\n"
    artifact.expires_at = timezone.now() - timedelta(seconds=1)
    artifact.required = True
    artifact.save(update_fields=["expires_at", "required"])
    assert expire_artifacts() == 0 and directory.exists()
    with pytest.raises(NodeExecutionError, match="unavailable"):
        execute_product(context, "relay/download-artifact@v1", {"name": "result"}, {}, node)
    artifact.required = False
    artifact.save(update_fields=["required"])
    (directory / "result.txt").write_bytes(b"corrupt")
    assert expire_artifacts() == 0 and directory.exists()
    (directory / "result.txt").write_bytes(b"original\n")
    assert expire_artifacts() == 1 and not directory.exists()
    assert not ActionsArtifact.objects.exists()
    with pytest.raises(NodeExecutionError, match="unavailable"):
        execute_product(context, "relay/download-artifact@v1", {"name": "missing"}, {}, node)


@pytest.mark.parametrize(
    "mode,expected", [("write", True), ("write-only", True), ("read", False), ("none", False)]
)
def test_cache_save_capability_and_immutability(
    product_context: tuple[AttemptContext, ActionsStepNode], mode: str, expected: bool
) -> None:
    context, node = product_context
    node = node.model_copy(update={"job": {**node.job, "cache-mode": mode}})
    execute_product(
        context, "relay/save-cache@v1", {"key": "exact", "path": "result.txt"}, {}, node
    )
    assert ActionsCache.objects.exists() is expected
    if expected:
        first = ActionsCache.objects.get()
        (context.worktree / "result.txt").write_bytes(b"changed\n")
        execute_product(
            context, "relay/save-cache@v1", {"key": "exact", "path": "result.txt"}, {}, node
        )
        assert ActionsCache.objects.get().pk == first.pk
        assert (Path(first.directory) / "result.txt").read_bytes() == b"original\n"


def test_cache_exact_prefix_restore_and_filesystem_warning(
    product_context: tuple[AttemptContext, ActionsStepNode], monkeypatch: pytest.MonkeyPatch
) -> None:
    context, node = product_context
    execute_product(
        context, "relay/save-cache@v1", {"key": "deps-v1", "path": "result.txt"}, {}, node
    )
    (context.worktree / "result.txt").unlink()
    exact = execute_product(
        context, "relay/restore-cache@v1", {"key": "deps-v1", "path": "result.txt"}, {}, node
    )
    assert exact.outputs["cache-hit"] == "true"
    assert (context.worktree / "result.txt").read_bytes() == b"original\n"
    prefix = execute_product(
        context,
        "relay/restore-cache@v1",
        {"key": "deps-v2", "restore-keys": "other\ndeps-", "path": "result.txt"},
        {},
        node,
    )
    assert (
        prefix.outputs["cache-hit"] == "false" and prefix.outputs["cache-matched-key"] == "deps-v1"
    )
    none = node.model_copy(update={"job": {**node.job, "cache-mode": "none"}})
    assert (
        execute_product(
            context, "relay/restore-cache@v1", {"key": "deps-v1", "path": "result.txt"}, {}, none
        ).outputs["cache-matched-key"]
        == ""
    )

    def unavailable(*args: Any, **kwargs: Any) -> None:
        message = "Disposable filesystem fault"
        raise OSError(message)

    monkeypatch.setattr("relay.web.actions_products.restore", unavailable)
    warned = execute_product(
        context, "relay/restore-cache@v1", {"key": "deps-v1", "path": "result.txt"}, {}, node
    )
    assert warned.outputs["cache-hit"] == "false"
    assert RunEvent.objects.filter(run_id=context.attempt.run_id, type="actions.warning").exists()


def test_cache_quota_evicts_oldest_verified_entry(
    product_context: tuple[AttemptContext, ActionsStepNode], monkeypatch: pytest.MonkeyPatch
) -> None:
    context, node = product_context
    execute_product(
        context, "relay/save-cache@v1", {"key": "first", "path": "result.txt"}, {}, node
    )
    first = ActionsCache.objects.get()
    monkeypatch.setattr("relay.web.actions_products.QUOTA", 9)
    execute_product(
        context, "relay/save-cache@v1", {"key": "second", "path": "result.txt"}, {}, node
    )
    assert list(ActionsCache.objects.values_list("key", flat=True)) == ["second"]
    assert not Path(first.directory).exists()


def test_cache_publication_race_removes_only_its_new_staging_directory(
    product_context: tuple[AttemptContext, ActionsStepNode], monkeypatch: pytest.MonkeyPatch
) -> None:
    context, node = product_context
    original = ActionsCache.objects.create
    directories: list[Path] = []

    def raced(**kwargs: Any) -> Any:
        directories.append(Path(kwargs["directory"]))
        message = "Another publisher won the unique key"
        raise IntegrityError(message)

    monkeypatch.setattr(ActionsCache.objects, "create", raced)
    execute_product(
        context, "relay/save-cache@v1", {"key": "raced", "path": "result.txt"}, {}, node
    )
    assert len(directories) == 1 and not directories[0].exists()
    assert not ActionsCache.objects.exists()
    monkeypatch.setattr(ActionsCache.objects, "create", original)


@pytest.mark.parametrize("key", ["", "x" * 513])
def test_invalid_cache_keys_fail_before_capture(
    product_context: tuple[AttemptContext, ActionsStepNode], key: str
) -> None:
    context, node = product_context
    with pytest.raises(NodeExecutionError, match="1 to 512"):
        execute_product(
            context, "relay/save-cache@v1", {"key": key, "path": "result.txt"}, {}, node
        )
    assert not ActionsCache.objects.exists()


def test_combined_cache_records_one_frozen_post_for_job_cleanup(
    product_context: tuple[AttemptContext, ActionsStepNode],
) -> None:
    from relay.execution.action_files import read_state
    from relay.web.actions_repository import job_state_path
    from relay.web.models import NodeRun

    context, node = product_context
    inputs = {"key": "deferred", "path": "result.txt"}
    result = execute_product(context, "relay/cache@v1", inputs, {}, node)
    assert result.outputs["cache-hit"] == "false" and not ActionsCache.objects.exists()
    job = NodeRun.objects.get(run_id=context.attempt.run_id, scope_path=node.state_scope)
    posts = read_state(job_state_path(str(job.pk)))["cache_posts"]
    assert len(posts) == 1 and posts[0]["inputs"] == inputs
    assert ActionsStepNode.model_validate(posts[0]["node"]) == node


def test_job_and_workflow_output_budgets_preserve_state_on_rejection(
    product_context: tuple[AttemptContext, ActionsStepNode],
) -> None:
    from relay.web.actions_repository import output_budget
    from relay.web.models import Run

    context, _ = product_context
    with pytest.raises(NodeExecutionError, match="1 MiB"):
        output_budget(context.attempt.attempt_id, {"value": "😀" * 262145})
    run = Run.objects.get(pk=context.attempt.run_id)
    state = dict(run.actions_state)
    state["output_sizes"] = {"upstream": 50 * 1048576}
    Run.objects.filter(pk=run.pk).update(actions_state=state)
    with pytest.raises(NodeExecutionError, match="50 MiB"):
        output_budget(context.attempt.attempt_id, {"value": "ready"})
    run.refresh_from_db()
    assert run.actions_state["output_sizes"] == {"upstream": 50 * 1048576}


def test_environment_links_omit_private_or_unsafe_urls(
    product_context: tuple[AttemptContext, ActionsStepNode],
) -> None:
    from relay.execution.masking import redactor
    from relay.web.actions_repository import publish_environment
    from relay.web.models import Run

    context, _ = product_context
    run_id = context.attempt.run_id
    redactor(run_id).register("private-token")
    for url in (
        "",
        "https://example.invalid/private-token",
        "https://[",
        "file:///private",
        "https://user:password@example.invalid",
        "https://example.invalid/" + "x" * 2048,
    ):
        publish_environment(context.attempt.attempt_id, "prod", url)
    assert not Run.objects.get(pk=run_id).actions_state.get("environment_links")
    publish_environment(context.attempt.attempt_id, "prod", "https://example.invalid/deploy")
    assert Run.objects.get(pk=run_id).actions_state["environment_links"][
        context.attempt.scope_path
    ] == {"name": "prod", "url": "https://example.invalid/deploy"}
