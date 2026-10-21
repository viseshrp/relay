"""Keep the starting tree of a scoped agent step so retries compare against it."""

from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: list[tuple[str, str]] = [  # noqa: RUF012
        ("relay_web", "0020_attempt_usage"),
    ]

    operations: list[Operation] = [  # noqa: RUF012
        migrations.AddField(
            model_name="noderun",
            name="write_baseline",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
    ]
