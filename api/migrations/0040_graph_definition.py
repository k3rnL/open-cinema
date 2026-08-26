import django.db.models.deletion
import uuid

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0039_orchestration_schema_state"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="GraphDefinition",
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
                    "kind",
                    models.CharField(
                        choices=[("graph", "Graph"), ("subgraph", "Subgraph")],
                        default="graph",
                        max_length=16,
                    ),
                ),
                ("labels", models.JSONField(blank=True, default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("archived_at", models.DateTimeField(blank=True, null=True)),
                (
                    "owner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="audio_graph_definitions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ("name", "id"),
                "indexes": [
                    models.Index(
                        fields=["owner", "kind"],
                        name="api_graph_owner_kind_idx",
                    ),
                    models.Index(
                        fields=["archived_at"],
                        name="api_graph_archived_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("owner", "name"),
                        name="api_graph_definition_owner_name_unique",
                    )
                ],
            },
        ),
    ]
