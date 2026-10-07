"""Assign stable project run numbers without changing execution history."""

from django.apps.registry import Apps
from django.db import migrations, models
from django.db.backends.base.schema import BaseDatabaseSchemaEditor
from django.db.migrations.operations.base import Operation
from django.utils import timezone
from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError


def number_existing_runs(apps: Apps, schema_editor: BaseDatabaseSchemaEditor) -> None:
    project_model = apps.get_model("relay_web", "Project")
    run_model = apps.get_model("relay_web", "Run")
    snapshot_model = apps.get_model("relay_web", "RunSnapshot")
    alias = schema_editor.connection.alias
    for project_id in project_model.objects.using(alias).values_list("pk", flat=True):
        rows = (
            run_model.objects.using(alias)
            .filter(project_id=project_id)
            .order_by("snapshot__created_at", "started_at", "pk")
        )
        for number, run in enumerate(rows, start=1):
            snapshot = snapshot_model.objects.using(alias).filter(run_id=run.pk).first()
            title = run.workflow_key
            created = run.started_at or timezone.now()
            if snapshot is not None:
                created = snapshot.created_at
                try:
                    document = YAML(typ="safe").load(snapshot.workflow_yaml)
                except YAMLError:
                    document = None
                if isinstance(document, dict) and isinstance(document.get("name"), str):
                    title = document["name"]
            run_model.objects.using(alias).filter(pk=run.pk).update(
                number=number, title=title, created_at=created
            )
        project_model.objects.using(alias).filter(pk=project_id).update(
            next_run_number=rows.count() + 1
        )


class Migration(migrations.Migration):
    dependencies: list[tuple[str, str]] = [("relay_web", "0009_run_repair_groups")]  # noqa: RUF012
    operations: list[Operation] = [  # noqa: RUF012
        migrations.AddField(
            model_name="project",
            name="next_run_number",
            field=models.PositiveIntegerField(default=1),
        ),
        migrations.AddField(
            model_name="run", name="number", field=models.PositiveIntegerField(default=0)
        ),
        migrations.AddField(
            model_name="run", name="title", field=models.TextField(blank=True, default="")
        ),
        migrations.AddField(
            model_name="run", name="source_branch", field=models.TextField(blank=True, null=True)
        ),
        migrations.AddField(
            model_name="run", name="created_at", field=models.DateTimeField(default=timezone.now)
        ),
        migrations.RunPython(number_existing_runs, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="run",
            constraint=models.UniqueConstraint(
                fields=("project", "number"),
                condition=models.Q(number__gt=0),
                name="relay_unique_project_run_number",
            ),
        ),
    ]
