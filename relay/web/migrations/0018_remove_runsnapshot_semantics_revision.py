"""Remove the unused workflow dialect discriminator."""

from django.db import migrations
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: list[tuple[str, str]] = [  # noqa: RUF012
        ("relay_web", "0017_remove_legacy_workflows"),
    ]

    operations: list[Operation] = [  # noqa: RUF012
        migrations.RemoveField(
            model_name="runsnapshot",
            name="semantics_revision",
        ),
    ]
