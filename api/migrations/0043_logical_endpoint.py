import django.db.models.deletion
import uuid

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0042_graph_activation"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="LogicalEndpoint",
            fields=[
                (
                    "id",
                    models.UUIDField(
                        default=uuid.uuid4,
                        editable=False,
                        primary_key=True,
                        serialize=False,
                    ),
                ),
                ("name", models.CharField(max_length=255)),
                (
                    "direction",
                    models.CharField(
                        choices=[("input", "Input"), ("output", "Output")],
                        max_length=16,
                    ),
                ),
                ("selector", models.JSONField(default=dict)),
                ("tags", models.JSONField(blank=True, default=list)),
                ("groups", models.JSONField(blank=True, default=list)),
                ("policy_metadata", models.JSONField(blank=True, default=dict)),
                ("explicit_binding", models.JSONField(blank=True, null=True)),
                ("last_known_summary", models.JSONField(blank=True, default=dict)),
                ("update_version", models.PositiveBigIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="logical_audio_endpoints",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("name", "id"),
                "indexes": [
                    models.Index(
                        fields=["owner", "direction"],
                        name="api_endpoint_owner_dir_idx",
                    ),
                    models.Index(
                        fields=["update_version"],
                        name="api_endpoint_update_ver_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("owner", "name"),
                        name="api_logical_endpoint_owner_name_unique",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("update_version__gte", 1)),
                        name="api_logical_endpoint_version_positive",
                    ),
                ],
            },
        ),
    ]
