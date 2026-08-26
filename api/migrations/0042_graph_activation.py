import django.db.models.deletion
import uuid

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0041_graph_revision"),
    ]

    operations = [
        migrations.CreateModel(
            name="GraphActivation",
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
                ("parameter_bindings", models.JSONField(blank=True, default=dict)),
                ("scene_bindings", models.JSONField(blank=True, default=dict)),
                ("desired_state_version", models.PositiveBigIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("activated_at", models.DateTimeField()),
                (
                    "definition",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="activation",
                        to="api.graphdefinition",
                    ),
                ),
                (
                    "revision",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="activations",
                        to="api.graphrevision",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["revision"],
                        name="api_activation_revision_idx",
                    ),
                    models.Index(
                        fields=["desired_state_version"],
                        name="api_activation_version_idx",
                    ),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(("desired_state_version__gte", 1)),
                        name="api_graph_activation_version_positive",
                    )
                ],
            },
        ),
    ]
