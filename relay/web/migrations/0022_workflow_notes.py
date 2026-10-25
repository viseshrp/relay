"""Store owner-approved workflow notes that launches can freeze."""

import uuid

from django.db import migrations, models
from django.db.migrations.operations.base import Operation
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies: list[tuple[str, str]] = [  # noqa: RUF012
        ("relay_web", "0021_noderun_write_baseline"),
    ]

    operations: list[Operation] = [  # noqa: RUF012
        migrations.CreateModel(
            name="WorkflowNote",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("workflow_key", models.TextField()),
                ("cue", models.TextField()),
                ("lesson", models.TextField()),
                ("evidence", models.TextField()),
                ("confidence", models.CharField(blank=True, max_length=8, null=True)),
                ("archived", models.BooleanField(default=False)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "evidence_run",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="+",
                        to="relay_web.run",
                    ),
                ),
                (
                    "project",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, to="relay_web.project"
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(fields=["project", "workflow_key"], name="relay_note_workflow_idx")
                ],
            },
        ),
    ]
