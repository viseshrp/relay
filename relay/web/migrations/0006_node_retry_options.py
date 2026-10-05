"""Keep owner retry choices separate from immutable launch snapshots."""

from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: list[tuple[str, str]] = [  # noqa: RUF012
        ("relay_web", "0005_process_creation_identity"),
    ]

    operations: list[Operation] = [  # noqa: RUF012
        migrations.AddField(
            model_name="noderun",
            name="retry_options",
            field=models.JSONField(default=dict),
        ),
    ]
