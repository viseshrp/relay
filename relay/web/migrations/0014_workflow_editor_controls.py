from django.db import migrations, models
from django.db.migrations.operations.base import Operation
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies: list[tuple[str, str]] = [("relay_web", "0013_actions_jobs_and_local_automation")]  # noqa: RUF012
    operations: list[Operation] = [  # noqa: RUF012
        migrations.CreateModel(
            name="WorkflowControl",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("workflow_key", models.TextField()),
                ("disabled", models.BooleanField(default=False)),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="relay_web.project"
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("project", "workflow_key"), name="relay_unique_workflow_control"
                    )
                ]
            },
        ),
    ]
