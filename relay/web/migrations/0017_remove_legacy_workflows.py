"""Remove v1 execution fields while retaining captured source and metadata."""

from __future__ import annotations

from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.operations.base import Operation


def _operation(value: object) -> object:
    if not isinstance(value, dict):
        return value
    result = dict(value)
    if result.get("type") in {"agent", "command"}:
        result.pop("writes", None)
        result.pop("inherit_env", None)
    for field in ("if", "on_timeout", "allow_no_commit"):
        result.pop(field, None)
    agents = result.get("bound_agents")
    if isinstance(agents, dict):
        result["bound_agents"] = {key: _operation(agent) for key, agent in agents.items()}
    if "bound_agent" in result:
        result["bound_agent"] = _operation(result["bound_agent"])
    return result


def preserve_and_normalize(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    """Normalize current compiled records without recompiling frozen source."""
    snapshots = apps.get_model("relay_web", "RunSnapshot")
    nodes = apps.get_model("relay_web", "NodeRun")
    database = schema_editor.connection.alias
    for snapshot in snapshots.objects.using(database).select_related("run").iterator():
        if snapshot.semantics_revision == "relay-local-1":
            plan = dict(snapshot.resolved_definition)
            for field in ("version", "model", "agents", "env", "inherit_env", "repairs"):
                plan.pop(field, None)
            records = plan.get("nodes")
            if isinstance(records, dict):
                plan["nodes"] = {key: _operation(node) for key, node in records.items()}
        else:
            # Unsupported snapshots remain opaque evidence. No runtime reads
            # this archive as a workflow or converts it into a current plan.
            plan = {
                "unsupported_snapshot": snapshot.resolved_definition,
                "removed_execution_metadata": {
                    "subworkflows": snapshot.subworkflows,
                    "default_model": snapshot.default_model,
                    "agent_prefs": snapshot.agent_prefs,
                    "repair_groups": snapshot.run.repair_groups,
                },
            }
        snapshots.objects.using(database).filter(pk=snapshot.pk).update(resolved_definition=plan)
    for node in nodes.objects.using(database).select_related("run__snapshot").iterator():
        if node.run.snapshot.semantics_revision == "relay-local-1":
            frozen = _operation(node.frozen_def)
        else:
            frozen = {
                **node.frozen_def,
                "removed_execution_metadata": {
                    "selected_branch": node.selected_branch,
                    "loop_index": node.loop_index,
                },
            }
        nodes.objects.using(database).filter(pk=node.pk).update(frozen_def=frozen)

    projects = apps.get_model("relay_web", "Project")
    for project in projects.objects.using(database).iterator():
        values = dict(project.defaults)
        defaults = values.get("workflow_defaults")
        if isinstance(defaults, dict) and "repairs" in defaults:
            values["workflow_defaults"] = {
                key: value for key, value in defaults.items() if key != "repairs"
            }
            projects.objects.using(database).filter(pk=project.pk).update(defaults=values)


class Migration(migrations.Migration):
    dependencies: list[tuple[str, str]] = [  # noqa: RUF012
        ("relay_web", "0016_dispatch_pause_time"),
    ]

    operations: list[Operation] = [  # noqa: RUF012
        migrations.RunPython(preserve_and_normalize, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="noderun",
            name="loop_index",
        ),
        migrations.RemoveField(
            model_name="noderun",
            name="selected_branch",
        ),
        migrations.RemoveField(
            model_name="run",
            name="repair_groups",
        ),
        migrations.RemoveField(
            model_name="runsnapshot",
            name="agent_prefs",
        ),
        migrations.RemoveField(
            model_name="runsnapshot",
            name="default_model",
        ),
        migrations.RemoveField(
            model_name="runsnapshot",
            name="subworkflows",
        ),
        migrations.AlterField(
            model_name="noderun",
            name="node_type",
            field=models.CharField(
                choices=[("actions_job", "Job"), ("actions_step", "Step")],
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="runsnapshot",
            name="semantics_revision",
            field=models.CharField(default="relay-local-1", max_length=64),
        ),
        migrations.DeleteModel(
            name="RunLock",
        ),
    ]
