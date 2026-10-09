"""Persist an owner hold without interrupting existing attempts."""

from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: list[tuple[str, str]] = [  # noqa: RUF012
        ("relay_web", "0007_automatic_recovery"),
    ]

    operations: list[Operation] = [  # noqa: RUF012
        migrations.AddField(
            model_name="run",
            name="dispatch_paused",
            field=models.BooleanField(default=False),
        ),
    ]
