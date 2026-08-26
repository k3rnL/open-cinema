import django.db.models.deletion
import uuid

from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0040_graph_definition"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="GraphRevision",
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
                ("schema_version", models.PositiveIntegerField(default=1)),
                ("revision_number", models.PositiveIntegerField()),
                (
                    "state",
                    models.CharField(
                        choices=[("draft", "Draft"), ("published", "Published")],
                        default="draft",
                        max_length=16,
                    ),
                ),
                ("content", models.JSONField()),
                ("content_digest", models.CharField(editable=False, max_length=64)),
                ("validation_summary", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("published_at", models.DateTimeField(blank=True, null=True)),
                (
                    "author",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="authored_audio_graph_revisions",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "definition",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="revisions",
                        to="api.graphdefinition",
                    ),
                ),
            ],
            options={
                "ordering": ("definition_id", "revision_number"),
                "indexes": [
                    models.Index(
                        fields=["definition", "state", "revision_number"],
                        name="api_graph_revision_state_idx",
                    ),
                    models.Index(
                        fields=["content_digest"],
                        name="api_graph_revision_digest_idx",
                    ),
                ],
                "constraints": [
                    models.UniqueConstraint(
                        fields=("definition", "revision_number"),
                        name="api_graph_revision_number_unique",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("schema_version__gte", 1)),
                        name="api_graph_revision_schema_positive",
                    ),
                    models.CheckConstraint(
                        condition=models.Q(("revision_number__gte", 1)),
                        name="api_graph_revision_number_positive",
                    ),
                    models.CheckConstraint(
                        condition=(
                            models.Q(("published_at__isnull", True), ("state", "draft"))
                            | models.Q(
                                ("published_at__isnull", False),
                                ("state", "published"),
                            )
                        ),
                        name="api_graph_revision_published_timestamp",
                    ),
                ],
            },
        ),
    ]
