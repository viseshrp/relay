"""Remove obsolete execution fields without losing captured run evidence."""

from hashlib import sha256

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
import pytest

from relay.errors import PersistenceError
from relay.web.models import NodeRun, RunSnapshot
from relay.web.repositories import DjangoExecutionStore, _compiled_run_graph
from relay.workflows.loader import load_workflow_text
from tests.support import RelayProject


def test_migration_preserves_current_plans_and_archives_unsupported_metadata(
    project: RelayProject,
) -> None:
    old = [("relay_web", "0016_dispatch_pause_time")]
    latest = [("relay_web", "0017_remove_legacy_workflows")]
    executor = MigrationExecutor(connection)
    executor.migrate(old)
    apps = executor.loader.project_state(old).apps
    run_model = apps.get_model("relay_web", "Run")
    snapshot_model = apps.get_model("relay_web", "RunSnapshot")
    node_model = apps.get_model("relay_web", "NodeRun")
    source = "name: Current\njobs: {work: {steps: [{run: print('ready'), shell: python}]}}\n"
    plan = load_workflow_text(source).definition.model_dump(mode="json", by_alias=True)
    plan.update(
        {"version": 1, "model": None, "agents": [], "env": {}, "inherit_env": True, "repairs": {}}
    )
    frozen = plan["nodes"]["work"]
    frozen.update({"if": None, "on_timeout": None, "allow_no_commit": True})
    frozen["bound_agents"] = {"root.work.check": {"type": "agent", "writes": False}}
    old_project = apps.get_model("relay_web", "Project")
    old_project.objects.filter(pk=project.project_id).update(
        defaults={
            "agent_preferences": ["codex"],
            "workflow_defaults": {"model": "m1", "repairs": {"max_rounds": 2}},
        }
    )
    hashes = {"workflow": sha256(source.encode()).hexdigest()}
    child = "version: 1\r\nname: Child Ω\r\nnodes: {}\r\n"
    legacy_source = "version: 1\nname: Old\nnodes: {}\n"
    try:
        runs = []
        for number, semantics, text, definition in [
            (1, "relay-local-1", source, plan),
            (2, "relay-v1", legacy_source, {}),
        ]:
            run = run_model.objects.create(
                project_id=project.project_id,
                number=number,
                workflow_key=f"workflow-{number}.yaml",
                source_commit="a" * 40,
                run_branch=f"relay/test/{number}",
                worktree_path=str(project.repository / f"run-{number}"),
                recorded_head="a" * 40,
                status="succeeded",
                repair_groups={"root.repairs": "root.review"} if number == 2 else {},
            )
            snapshot_model.objects.create(
                run=run,
                workflow_yaml=text,
                semantics_revision=semantics,
                resolved_definition=definition,
                subworkflows={"child.yaml": {"yaml": child}} if number == 2 else {},
                default_model="exact-model" if number == 2 else "",
                agent_prefs=[{"agents": ["codex"]}] if number == 2 else [],
                relay_version="test",
                hashes=hashes,
            )
            node_model.objects.create(
                run=run,
                scope_path="root.work",
                node_id="work",
                node_type="actions_job" if number == 1 else "loop",
                frozen_def=frozen if number == 1 else {"type": "loop"},
                status="succeeded",
                selected_branch="done" if number == 2 else None,
                loop_index=2 if number == 2 else None,
            )
            runs.append(str(run.pk))
        executor = MigrationExecutor(connection)
        executor.migrate(latest)

        current = RunSnapshot.objects.get(run_id=runs[0])
        assert current.workflow_yaml == source
        assert current.hashes == hashes
        assert "version" not in current.resolved_definition
        current_node = NodeRun.objects.get(run_id=runs[0])
        assert "allow_no_commit" not in current_node.frozen_def
        assert "if" not in current_node.frozen_def
        assert "writes" not in current_node.frozen_def["bound_agents"]["root.work.check"]
        from relay.web.models import Project

        assert Project.objects.get(pk=project.project_id).defaults == {
            "agent_preferences": ["codex"],
            "workflow_defaults": {"model": "m1"},
        }
        _compiled_run_graph.cache_clear()
        assert tuple(DjangoExecutionStore().run_graph(runs[0]).nodes) == ("work",)

        unsupported = RunSnapshot.objects.get(run_id=runs[1])
        assert unsupported.workflow_yaml == legacy_source
        assert unsupported.hashes == hashes
        archived = unsupported.resolved_definition["removed_execution_metadata"]
        assert archived["subworkflows"] == {"child.yaml": {"yaml": child}}
        assert archived["default_model"] == "exact-model"
        assert archived["agent_prefs"] == [{"agents": ["codex"]}]
        assert archived["repair_groups"] == {"root.repairs": "root.review"}
        retained = NodeRun.objects.get(run_id=runs[1]).frozen_def
        assert retained["removed_execution_metadata"] == {
            "selected_branch": "done",
            "loop_index": 2,
        }
        with pytest.raises(PersistenceError):
            DjangoExecutionStore().run_graph(runs[1])
    finally:
        MigrationExecutor(connection).migrate(latest)
        _compiled_run_graph.cache_clear()
