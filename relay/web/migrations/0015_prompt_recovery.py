from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: list[tuple[str, str]] = [("relay_web", "0014_workflow_editor_controls")]  # noqa: RUF012
    operations: list[Operation] = [  # noqa: RUF012
        migrations.AddField(
            model_name="workflowdraft", name="prompt_edits", field=models.JSONField(default=dict)
        ),
    ]
