"""Keep legacy repair presentation separate from immutable workflow snapshots."""

from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: list[tuple[str, str]] = [("relay_web", "0008_run_dispatch_paused")]  # noqa: RUF012

    operations: list[Operation] = [  # noqa: RUF012
        migrations.AddField(
            model_name="run", name="repair_groups", field=models.JSONField(default=dict)
        ),
    ]
