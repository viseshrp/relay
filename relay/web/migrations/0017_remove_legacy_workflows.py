"""Apply the job and step execution schema."""

from __future__ import annotations

from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: list[tuple[str, str]] = [  # noqa: RUF012
        ("relay_web", "0016_dispatch_pause_time"),
    ]

    operations: list[Operation] = [  # noqa: RUF012
        migrations.RemoveField(
            model_name="noderun",
            name="loop_index",
        ),
        migrations.RemoveField(
            model_name="noderun",
            name="selected_branch",
        ),
        migrations.RemoveField(
            model_name="run",
            name="repair_groups",
        ),
        migrations.RemoveField(
            model_name="runsnapshot",
            name="agent_prefs",
        ),
        migrations.RemoveField(
            model_name="runsnapshot",
            name="default_model",
        ),
        migrations.RemoveField(
            model_name="runsnapshot",
            name="subworkflows",
        ),
        migrations.AlterField(
            model_name="noderun",
            name="node_type",
            field=models.CharField(
                choices=[("actions_job", "Job"), ("actions_step", "Step")],
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="runsnapshot",
            name="semantics_revision",
            field=models.CharField(default="relay-local-1", max_length=64),
        ),
        migrations.DeleteModel(
            name="RunLock",
        ),
    ]
