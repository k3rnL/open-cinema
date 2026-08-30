import uuid

import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("api", "0053_graph_activation_enabled"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="SystemControlOperation",
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
                (
                    "correlation_id",
                    models.UUIDField(default=uuid.uuid4, editable=False, unique=True),
                ),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("restart-open-cinema", "Restart Open Cinema"),
                            ("restart-orchestrator", "Restart audio orchestrator"),
                            ("reboot-appliance", "Reboot appliance"),
                        ],
                        max_length=32,
                    ),
                ),
                ("target_id", models.CharField(max_length=64)),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("requested", "Requested"),
                            ("executing", "Executing"),
                            ("reconnecting", "Reconnecting"),
                            ("succeeded", "Succeeded"),
                            ("failed", "Failed"),
                        ],
                        default="requested",
                        max_length=16,
                    ),
                ),
                ("initial_boot_id", models.CharField(blank=True, max_length=64)),
                ("initial_service_instance", models.CharField(blank=True, max_length=128)),
                ("error_code", models.CharField(blank=True, max_length=64)),
                ("error_detail", models.CharField(blank=True, max_length=512)),
                ("requested_at", models.DateTimeField(auto_now_add=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                (
                    "requested_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="system_control_operations",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={"ordering": ("-requested_at",)},
        ),
        migrations.AddIndex(
            model_name="systemcontroloperation",
            index=models.Index(
                fields=["action", "status", "requested_at"],
                name="api_sysctl_action_state_idx",
            ),
        ),
        migrations.AddConstraint(
            model_name="systemcontroloperation",
            constraint=models.CheckConstraint(
                condition=~models.Q(("target_id", "")),
                name="api_system_control_target_nonempty",
            ),
        ),
    ]
