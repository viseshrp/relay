"""Retain provider-reported attempt tokens and cost as nullable diagnostics."""

from django.db import migrations, models
from django.db.migrations.operations.base import Operation


class Migration(migrations.Migration):
    dependencies: list[tuple[str, str]] = [  # noqa: RUF012
        ("relay_web", "0019_alter_nodeattempt_stop_reason"),
    ]

    operations: list[Operation] = [  # noqa: RUF012
        migrations.AddField(
            model_name="nodeattempt",
            name="cached_read_tokens",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="nodeattempt",
            name="cached_write_tokens",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="nodeattempt",
            name="cost_amount",
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="nodeattempt",
            name="cost_currency",
            field=models.CharField(blank=True, max_length=16, null=True),
        ),
        migrations.AddField(
            model_name="nodeattempt",
            name="input_tokens",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="nodeattempt",
            name="output_tokens",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="nodeattempt",
            name="thought_tokens",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name="nodeattempt",
            name="total_tokens",
            field=models.PositiveBigIntegerField(blank=True, null=True),
        ),
    ]
