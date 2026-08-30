import uuid

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("api", "0054_system_control_operation")]

    operations = [
        migrations.CreateModel(
            name="MasterAudioLevel",
            fields=[
                (
                    "id",
                    models.PositiveSmallIntegerField(
                        default=1, editable=False, primary_key=True, serialize=False
                    ),
                ),
                ("level", models.FloatField(default=1.0)),
                ("muted", models.BooleanField(default=False)),
                ("update_version", models.PositiveBigIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.CreateModel(
            name="EndpointAudioLevel",
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
                ("level", models.FloatField(default=1.0)),
                ("muted", models.BooleanField(default=False)),
                ("update_version", models.PositiveBigIntegerField(default=1)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "endpoint",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="audio_level",
                        to="api.logicalendpoint",
                    ),
                ),
            ],
        ),
        migrations.AddConstraint(
            model_name="masteraudiolevel",
            constraint=models.CheckConstraint(
                condition=models.Q(("id", 1)), name="api_master_audio_singleton"
            ),
        ),
        migrations.AddConstraint(
            model_name="masteraudiolevel",
            constraint=models.CheckConstraint(
                condition=models.Q(("update_version__gte", 1)),
                name="api_master_audio_version_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="masteraudiolevel",
            constraint=models.CheckConstraint(
                condition=models.Q(("level__gte", 0.0), ("level__lte", 1.0)),
                name="api_master_audio_level_range",
            ),
        ),
        migrations.AddConstraint(
            model_name="endpointaudiolevel",
            constraint=models.CheckConstraint(
                condition=models.Q(("update_version__gte", 1)),
                name="api_endpoint_audio_version_positive",
            ),
        ),
        migrations.AddConstraint(
            model_name="endpointaudiolevel",
            constraint=models.CheckConstraint(
                condition=models.Q(("level__gte", 0.0), ("level__lte", 1.0)),
                name="api_endpoint_audio_level_range",
            ),
        ),
    ]
