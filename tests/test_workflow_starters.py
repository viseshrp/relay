"""Starter bundles validate, preserve exact bytes, and never replace owner files."""

from __future__ import annotations

from pathlib import Path

import pytest

from relay.errors import PathSafetyError, PermissionFlowError, WorkflowValidationError
from relay.web.repositories import DjangoWorkflowStore
from relay.workflows import starters
from relay.workflows.loader import load_workflow
from relay.workflows.starters import (
    STARTER_ROOT,
    STARTERS,
    create_starter_workflow,
    starter_inventory,
)
from relay.workflows.validation import validate_loaded_workflow
from tests.support import (
    FakeAgents,
    InlineEngine,
    RelayProject,
    fake_executable,
    run_status,
    symlink_or_skip,
)


@pytest.mark.parametrize("starter", STARTERS, ids=lambda item: item.id)
def test_starter_copies_exact_sources_and_validates(
    project: RelayProject,
    starter: starters.Starter,
) -> None:
    key = f"{starter.id}.yaml"
    document = create_starter_workflow(
        DjangoWorkflowStore(), project.relay_root, project.project_id, key, starter.id
    )
    assert document.yaml.encode() == (STARTER_ROOT / key).read_bytes()
    for name in starter.prompts:
        assert (project.relay_root / "prompts" / name).read_bytes() == (
            STARTER_ROOT / name
        ).read_bytes()
    validate_loaded_workflow(
        load_workflow(project.relay_root / "workflows" / key), project.relay_root
    )
    second = create_starter_workflow(
        DjangoWorkflowStore(), project.relay_root, project.project_id, f"second-{key}", starter.id
    )
    assert second.yaml == document.yaml


def test_gallery_has_six_templates_and_schema_defined_inputs() -> None:
    inventory = starter_inventory()
    assert len(inventory) == 6
    assert all(item["jobs"] and item["required_agents"] for item in inventory)
    assert inventory[0]["inputs"] == {
        "task": {
            "type": "string",
            "description": "What would you like to learn about this repository?",
            "default": "Explain what this repository does and where its main code lives.",
            "required": True,
            "constraints": {"min_length": None, "max_length": None, "pattern": None},
        },
    }


def test_starter_rejects_unknown_id_and_unsafe_key(project: RelayProject) -> None:
    store = DjangoWorkflowStore()
    with pytest.raises(WorkflowValidationError):
        create_starter_workflow(
            store, project.relay_root, project.project_id, "new.yaml", "unknown"
        )
    with pytest.raises(WorkflowValidationError):
        create_starter_workflow(
            store, project.relay_root, project.project_id, "../new.yaml", "ask-agent"
        )
    with pytest.raises(WorkflowValidationError):
        create_starter_workflow(
            store, project.relay_root, project.project_id, "CON.yaml", "ask-agent"
        )


def test_starter_preserves_existing_prompts_and_workflows(project: RelayProject) -> None:
    prompt = project.relay_root / "prompts" / "ask-agent.md"
    prompt.write_bytes(b"Owner instructions\n")
    with pytest.raises(PermissionFlowError):
        create_starter_workflow(
            DjangoWorkflowStore(), project.relay_root, project.project_id, "new.yaml", "ask-agent"
        )
    assert prompt.read_bytes() == b"Owner instructions\n"
    assert not (project.relay_root / "workflows" / "new.yaml").exists()
    with pytest.raises(PermissionFlowError):
        create_starter_workflow(
            DjangoWorkflowStore(),
            project.relay_root,
            project.project_id,
            "workflow.yaml",
            "write-docs",
        )
    assert not (project.relay_root / "prompts" / "write-docs.md").exists()


def test_starter_rolls_back_new_prompts_on_write_failure(
    project: RelayProject,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = starters._atomic_create

    def fail_workflow(path: Path, text: str) -> None:
        if path.suffix == ".yaml":
            message = "Could not publish."
            raise PermissionFlowError(message)
        original(path, text)

    monkeypatch.setattr(starters, "_atomic_create", fail_workflow)
    with pytest.raises(PermissionFlowError):
        create_starter_workflow(
            DjangoWorkflowStore(),
            project.relay_root,
            "project",
            "new.yaml",
            "plan-approve-implement",
        )
    assert not (project.relay_root / "workflows" / "new.yaml").exists()
    assert not (project.relay_root / "prompts" / "plan.md").exists()
    assert not (project.relay_root / "prompts" / "implement.md").exists()


def test_starter_rejects_symlink_escape(project: RelayProject, tmp_path: Path) -> None:
    outside = tmp_path / "outside.md"
    outside.write_bytes(b"Owner bytes")
    symlink_or_skip(project.relay_root / "prompts" / "ask-agent.md", outside)
    with pytest.raises(PathSafetyError):
        create_starter_workflow(
            DjangoWorkflowStore(), project.relay_root, project.project_id, "new.yaml", "ask-agent"
        )
    assert outside.read_bytes() == b"Owner bytes"


@pytest.mark.usefixtures("registry_network", "database_threads")
@pytest.mark.parametrize("passes_on,status,checks", [(2, "succeeded", 2), (99, "failed", 3)])
def test_fix_tests_starter_uses_real_verdicts_and_a_bounded_repair_budget(
    project: RelayProject,
    engine: InlineEngine,
    fake_agents: FakeAgents,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    passes_on: int,
    status: str,
    checks: int,
) -> None:
    counter = tmp_path / "test-counter"
    counter.write_text("0", encoding="utf-8")
    monkeypatch.setenv("STARTER_TEST_COUNTER", str(counter))
    monkeypatch.setenv("STARTER_TEST_PASSES_ON", str(passes_on))
    fake_agents.install("codex", mode="configuration")
    fake_executable(
        fake_agents.directory,
        "python",
        ("import os, sys\nos.execv(sys.executable, [sys.executable, *sys.argv[1:]])\n"),
    )
    project.write(".gitignore", "__pycache__/\n.pytest_cache/\n")
    project.write(
        "test_example.py",
        (
            "import os\nfrom pathlib import Path\n"
            "def test_result():\n"
            "    counter = Path(os.environ['STARTER_TEST_COUNTER'])\n"
            "    count = int(counter.read_text()) + 1\n"
            "    counter.write_text(str(count))\n"
            "    assert count >= int(os.environ['STARTER_TEST_PASSES_ON'])\n"
        ),
    )
    project.commit("Add deterministic sample tests")
    create_starter_workflow(
        DjangoWorkflowStore(), project.relay_root, project.project_id, "fix.yaml", "fix-tests"
    )
    run_id = engine.launch(project, "fix.yaml", model="m1")
    engine.drain(run_id)
    assert run_status(run_id) == status
    assert counter.read_text(encoding="utf-8") == str(checks)
