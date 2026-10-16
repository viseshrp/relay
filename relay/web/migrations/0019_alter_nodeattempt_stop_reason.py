"""Keep attempt stop reasons limited to Relay execution states."""

from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: list[tuple[str, str]] = [  # noqa: RUF012
        ("relay_web", "0018_remove_runsnapshot_semantics_revision"),
    ]

    operations: list[Operation] = [  # noqa: RUF012
        migrations.AlterField(
            model_name="nodeattempt",
            name="stop_reason",
            field=models.CharField(
                blank=True,
                choices=[
                    ("completed", "Completed"),
                    ("failed", "Failed"),
                    ("output_invalid", "Output invalid"),
                    ("timeout", "Timeout"),
                    ("canceled", "Canceled"),
                    ("worker_lost", "Worker lost"),
                    ("interrupted", "Interrupted"),
                ],
                max_length=16,
                null=True,
            ),
        ),
    ]
