"""Persist recovery policies, bounded decisions, and separate repair instructions."""

from django.db import migrations, models
from django.db.migrations.operations.base import Operation
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies: list[tuple[str, str]] = [  # noqa: RUF012
        ("relay_web", "0006_node_retry_options"),
    ]

    operations: list[Operation] = [  # noqa: RUF012
        migrations.AddField(
            model_name="noderun",
            name="recovery_instruction",
            field=models.TextField(blank=True, default=""),
        ),
        migrations.AddField(
            model_name="run",
            name="recovery_policy",
            field=models.JSONField(default=dict),
        ),
        migrations.CreateModel(
            name="AutomaticRetry",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True, primary_key=True, serialize=False, verbose_name="ID"
                    ),
                ),
                ("retry_number", models.PositiveIntegerField()),
                ("state", models.CharField(default="scheduled", max_length=16)),
                ("instruction", models.TextField(blank=True)),
                ("instruction_sha256", models.CharField(blank=True, max_length=64)),
                ("error_message", models.TextField(blank=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "attempt",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="automatic_retry",
                        to="relay_web.nodeattempt",
                    ),
                ),
            ],
            options={
                "indexes": [models.Index(fields=["state"], name="relay_auto_retry_state_idx")],
            },
        ),
    ]
