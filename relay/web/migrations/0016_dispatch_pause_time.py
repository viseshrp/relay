from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: list[tuple[str, str]] = [("relay_web", "0015_prompt_recovery")]  # noqa: RUF012
    operations: list[Operation] = [  # noqa: RUF012
        migrations.AddField(
            "run", "dispatch_paused_at", models.DateTimeField(null=True, blank=True)
        ),
        migrations.AddField("run", "dispatch_paused_seconds", models.FloatField(default=0)),
    ]
