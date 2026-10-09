"""Keep opt-in integration recoverable without changing existing runs."""

from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: list[tuple[str, str]] = [("relay_web", "0011_settings_defaults")]  # noqa: RUF012
    operations: list[Operation] = [  # noqa: RUF012
        migrations.AddField(
            model_name="run",
            name="merged_commit",
            field=models.CharField(max_length=40, null=True, blank=True),
        ),
        migrations.AlterField(
            model_name="run",
            name="cleanup_policy",
            field=models.CharField(
                max_length=20,
                default="clean_on_success",
                choices=[
                    ("clean_on_success", "Clean on success"),
                    ("retain", "Retain"),
                    ("merge_on_success", "Merge and clean on success"),
                ],
            ),
        ),
        migrations.AlterField(
            model_name="run",
            name="status",
            field=models.CharField(
                max_length=16,
                default="pending",
                choices=[
                    ("pending", "Pending"),
                    ("running", "Running"),
                    ("completing", "Merging and cleaning up"),
                    ("paused_wait", "Paused for input"),
                    ("canceling", "Canceling"),
                    ("succeeded", "Succeeded"),
                    ("failed", "Failed"),
                    ("canceled", "Canceled"),
                    ("interrupted", "Interrupted"),
                ],
            ),
        ),
    ]
