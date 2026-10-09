"""Keep project overrides and captured launch defaults without rewriting history."""

from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: list[tuple[str, str]] = [("relay_web", "0010_run_identity")]  # noqa: RUF012
    operations: list[Operation] = [  # noqa: RUF012
        migrations.AddField(
            model_name="project", name="defaults", field=models.JSONField(default=dict)
        ),
        migrations.AddField(
            model_name="runsnapshot", name="launch_defaults", field=models.JSONField(default=dict)
        ),
    ]
